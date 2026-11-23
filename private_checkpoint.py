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

from study import canonical


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

    def decision(self, operation, criteria):
        row = self.data['segments'][self.cursor]
        self.cursor += 1
        if row['status'] == 'ok':
            if row['label'] not in criteria:
                raise ValueError('checkpoint_incomplete')
            return row['label']
        if self.paused:
            return None
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
