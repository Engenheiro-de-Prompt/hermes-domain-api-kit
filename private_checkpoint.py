"""Private minimal journal: opaque identities and enum decisions, never payloads.

Single writer; write-ahead unknown state makes interrupted sends non-replayable.
The directory must stay private and intact, outside report exports.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import tempfile
import math
import time

from study import canonical

_TRANSIENT = frozenset({'http_502', 'http_503', 'http_504', 'timeout', 'transport_error'})
_RETRY_ERRORS = _TRANSIENT | {'capacity_busy'}


def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic(path, value):
    atomic_text(path, canonical(value) + '\n')


def atomic_text(path, body):
    fd, temp = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


class Journal:
    def __init__(self, path, resume, contract, identities, allowed):
        self.path = Path(path)
        self.lock = None
        if any(p.is_symlink() for p in (self.path, *self.path.parents)):
            raise ValueError('invalid_work')
        if not self.path.exists():
            if resume:
                raise ValueError('checkpoint_incomplete')
            self.path.mkdir(mode=0o700, parents=True)
            sync_directory(self.path.parent)
        elif not resume:
            raise ValueError('private_output_exists')
        if os.name == 'posix' and self.path.stat().st_mode & 0o077:
            raise ValueError('insecure_output_permissions')
        # Reject links and unexpected files rather than adopting somebody else's state.
        if any(p.is_symlink() or not p.is_file() or p.stat().st_nlink != 1 for p in self.path.iterdir()):
            raise ValueError('checkpoint_incomplete')
        fd = os.open(self.path / 'lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.lock = os.fdopen(fd, 'r+b')
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                self.lock.seek(0); self.lock.write(b'0'); self.lock.flush(); self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.close()
            raise ValueError('pipeline_busy') from None
        try:
            state_path = self.path / 'state.json'
            done_path = self.path / 'completed.json'
            if resume:
                chosen = done_path if done_path.exists() else state_path
                if not chosen.is_file():
                    raise ValueError('checkpoint_incomplete')
                self.data = json.loads(chosen.read_text(encoding='utf-8'))
                self.salt = bytes.fromhex(self.data['salt'])
                if self.data['contract'] != self.hash(contract):
                    raise ValueError('campaign_mismatch')
                hashes = [self.hash(i) for i in identities]
                if self.data['identity'] != self.hash(hashes):
                    raise ValueError('campaign_mismatch')
                self.done = chosen == done_path
                if not self.done:
                    segments = self.data['segments']
                    if len(segments) != len(hashes):
                        raise ValueError('checkpoint_incomplete')
                    for row, identity, criteria in zip(segments, hashes, allowed):
                        if (set(row) != {'hash', 'status', 'label'} or row['hash'] != identity
                                or row['status'] not in ('pending', 'unknown', 'ok')
                                or (row['status'] == 'ok') != isinstance(row['label'], str)
                                or row['status'] == 'ok' and row['label'] not in criteria
                                or row['status'] != 'ok' and row['label'] is not None):
                            raise ValueError('checkpoint_incomplete')
            else:
                self.salt = secrets.token_bytes(32)
                hashes = [self.hash(i) for i in identities]
                self.data = {'version': 1, 'salt': self.salt.hex(), 'contract': self.hash(contract),
                             'identity': self.hash(hashes), 'model': None,
                             'segments': [{'hash': h, 'status': 'pending', 'label': None} for h in hashes]}
                self.done = False
                self.save()
            self.cursor = 0
            self.retry_attempts = 1
            self.retry_backoff = 0
            self.retry_enabled = False
            self.progress = None
            self._validate_recovery()
            self.paused = not self.done and any(r['status'] == 'unknown' for r in self.data['segments'])
            self.failure_code = 'uncertain_previous_request' if self.paused else None
        except BaseException:
            self.close()
            raise

    def hash(self, value):
        return hmac.new(self.salt, canonical(value).encode('utf-8'), hashlib.sha256).hexdigest()

    def save(self):
        atomic(self.path / 'state.json', self.data)

    def bind_model(self, model):
        hashed = self.hash(model)
        if self.data['model'] not in (None, hashed):
            raise ValueError('campaign_mismatch')
        self.data['model'] = hashed
        self.save()

    def _validate_recovery(self):
        meta = self.data.get('recovery')
        if meta is None:
            return
        if (not isinstance(meta, dict)
                or set(meta) != {'version', 'attempts', 'retries', 'uncertain_replays', 'errors', 'retryable'}
                or type(meta['version']) is not int or meta['version'] != 1
                or any(type(meta[k]) is not int or meta[k] < 0 for k in ('attempts', 'retries', 'uncertain_replays'))
                or not isinstance(meta['errors'], dict)
                or any(k not in _RETRY_ERRORS or type(v) is not int or v < 0 for k, v in meta['errors'].items())
                or not isinstance(meta['retryable'], list)
                or any(not isinstance(h, str) for h in meta['retryable'])
                or len(meta['retryable']) != len(set(meta['retryable']))):
            raise ValueError('checkpoint_incomplete')
        unknown = {r['hash'] for r in self.data.get('segments', []) if r['status'] == 'unknown'}
        if set(meta['retryable']) - unknown:
            raise ValueError('checkpoint_incomplete')

    def enable_retry(self, *, max_attempts=6, backoff=1, recover_uncertain=False, progress=None):
        """Explicit at-least-once policy, after source/model/privacy preflight.

        Unknown legacy sends are adopted ONLY with the separate operator flag.
        Confirmed labels and the frozen contract never change.
        """
        if (type(max_attempts) is not int or not 1 <= max_attempts <= 100
                or type(backoff) not in (int, float) or not math.isfinite(backoff)
                or not 0 <= backoff <= 60 or type(recover_uncertain) is not bool):
            raise ValueError('invalid_retry_policy')
        if self.done:
            return
        self.retry_enabled = True
        self.retry_attempts = max_attempts
        self.retry_backoff = backoff
        self.progress = progress
        meta = self.data.setdefault('recovery', {'version': 1, 'attempts': 0, 'retries': 0,
                                               'uncertain_replays': 0, 'errors': {}, 'retryable': []})
        unknown = {r['hash'] for r in self.data['segments'] if r['status'] == 'unknown'}
        if recover_uncertain:
            meta['retryable'] = sorted(unknown)
        self.paused = bool(unknown - set(meta['retryable']))
        self.failure_code = 'uncertain_previous_request' if self.paused else None
        self.save()

    def recovery_stats(self):
        meta = self.data.get('recovery')
        return ({'policy': 'at_least_once', 'counter_scope': 'since_retry_policy_enabled',
                 **{k: v for k, v in meta.items() if k not in ('version', 'retryable')}}
                if meta is not None else {'policy': 'strict_no_replay'})

    def _progress(self, event):
        if self.progress is not None:
            counts = {status: sum(r['status'] == status for r in self.data['segments'])
                      for status in ('ok', 'unknown', 'pending')}
            self.progress({'event': event, 'confirmed': counts['ok'], 'unknown': counts['unknown'],
                           'pending': counts['pending'], 'planned': len(self.data['segments']),
                           'attempts': self.data['recovery']['attempts'],
                           'retries': self.data['recovery']['retries']})

    def decision(self, operation, criteria):
        row = self.data['segments'][self.cursor]
        self.cursor += 1
        if row['status'] == 'ok':
            if row['label'] not in criteria:
                raise ValueError('checkpoint_incomplete')
            return row['label']
        if self.paused:
            return None
        if self.retry_enabled:
            return self._retry_decision(row, operation, criteria)
        row['status'] = 'unknown'
        self.save()  # write-ahead, before the request can leave this process
        try:
            label = operation()
        except Exception as error:
            self.paused = True
            from api_client import ClientError
            if isinstance(error, ClientError) and error.code == 'capacity_busy' and error.admission_not_started:
                row['status'] = 'pending'
                self.save()  # rejection was confirmed before execution; resume only
                self.failure_code = 'capacity_busy'
                return None
            allowed = {'http_429', 'http_503', 'http_504', 'http_401', 'http_403',
                       'timeout', 'transport_error', 'privacy_confirmation_missing',
                       'invalid_json', 'invalid_schema', 'response_too_large', 'api_error'}
            self.failure_code = error.code if isinstance(error, ClientError) and error.code in allowed else 'classification_response_unconfirmed'
            return None  # sanitized status remains durable; no raw error persisted
        row.update(status='ok', label=label)
        self.save()  # failure propagates, preventing any next request
        return label

    def _retry_decision(self, row, operation, criteria):
        from api_client import ClientError
        meta = self.data['recovery']
        for attempt in range(self.retry_attempts):
            was_unknown = row['status'] == 'unknown'
            if was_unknown and row['hash'] not in meta['retryable']:
                self.paused = True
                self.failure_code = 'uncertain_previous_request'
                return None
            if attempt or was_unknown:
                meta['retries'] += 1
            if was_unknown:
                meta['uncertain_replays'] += 1
            meta['attempts'] += 1
            row['status'] = 'unknown'
            if row['hash'] not in meta['retryable']:
                meta['retryable'].append(row['hash'])
            self.save()  # mandatory barrier before EVERY external attempt
            try:
                label = operation()
                if not isinstance(label, str) or label not in criteria:
                    raise ValueError('classification_response_unconfirmed')
            except Exception as error:
                code = error.code if isinstance(error, ClientError) else 'classification_response_unconfirmed'
                proven_capacity = (isinstance(error, ClientError) and code == 'capacity_busy'
                                   and error.admission_not_started)
                transient = isinstance(error, ClientError) and code in _TRANSIENT
                if not transient and not proven_capacity:
                    meta['retryable'].remove(row['hash'])
                    self.paused = True
                    safe = {'http_429', 'http_401', 'http_403', 'privacy_confirmation_missing',
                            'invalid_json', 'invalid_schema', 'response_too_large', 'api_error'}
                    self.failure_code = code if code in safe else 'classification_response_unconfirmed'
                    self.save()
                    self._progress('blocked')
                    return None
                meta['errors'][code] = meta['errors'].get(code, 0) + 1
                if proven_capacity:
                    row['status'] = 'pending'
                    meta['retryable'].remove(row['hash'])
                self.failure_code = 'transient_retry_exhausted'
                self.save()  # retry/error accounting is durable before another request
                self._progress('retry' if attempt + 1 < self.retry_attempts else 'deferred')
                if attempt + 1 < self.retry_attempts:
                    delay = min(60, self.retry_backoff * 2 ** attempt)
                    hint = getattr(error, 'retry_after', None)
                    if type(hint) is int and 1 <= hint <= 60:
                        delay = max(delay, hint)
                    time.sleep(delay)
                    continue
                return None  # keep the gap; independent segments may still complete
            row.update(status='ok', label=label)
            meta['retryable'].remove(row['hash'])
            self.save()  # outside error handling: persistence failure stops all work
            if self.cursor % 25 == 0 or self.cursor == len(self.data['segments']):
                self._progress('confirmed')
            return label
        return None

    def finish(self, exports):
        if any(r['status'] != 'ok' for r in self.data['segments']):
            raise ValueError('checkpoint_incomplete')
        marker = {k: v for k, v in self.data.items() if k != 'segments'}
        marker['confirmed'] = len(self.data['segments'])
        marker['exports'] = exports
        atomic(self.path / 'completed.json', marker)
        self.cleanup_completed()

    def cleanup_completed(self):
        # Caller must first validate all completed exports on resume.
        (self.path / 'state.json').unlink(missing_ok=True)
        # Only our own abandoned atomic-write scratch files; never recurse/remove unknown files.
        for path in self.path.glob('.write-*'):
            path.unlink()
        sync_directory(self.path)

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None
