"""Opt-in full CLI/HTTP campaign recovery proof. SYNTHETIC DATA ONLY.

No real profile, API credentials, cloud, LLM or model. Private workdir outside
checkout; server exposes only synthetic responses on random loopback port.
"""
import argparse
from collections import Counter
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workdir', required=True)
    p.add_argument('--events', type=int, default=2640)
    args = p.parse_args()
    if args.events < 77:
        raise ValueError('need_at_least_77_events_for_304_prefix')
    os.umask(0o077)
    root = Path(args.workdir).resolve()
    if root.exists() or ROOT == root or ROOT in root.parents:
        raise ValueError('fresh_external_synthetic_work_required')
    root.mkdir(parents=True, mode=0o700)
    source = root / 'synthetic-events.json'
    source.write_text(json.dumps({'schema_version': 1, 'events': [
        {'event_id': 'SYNTHETIC-EVENT-' + str(i), 'tenant_id': 'synthetic-proof',
         'source_id': 'synthetic-source', 'session_id': 'synthetic-session',
         'event_type': 'request', 'timestamp': 1704067200 + i, 'actor': 'user',
         'source_complete': False, 'task_id': 'SYNTHETIC-TASK-' + str(i),
         'text': 'SYNTHETIC-TEXT-NOT-REAL-HISTORY ' + str(i)} for i in range(args.events)]}), encoding='utf-8')
    key = root / 'synthetic-client'; key.write_text('synthetic-only-not-a-credential'); key.chmod(0o600)
    seen = Counter(); confirmed = set(); old_prefix = set(); counts = Counter(); stage = [0]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass
        def reply(self, status, body):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers(); self.wfile.write(data)
        def do_GET(self):
            self.reply(200, {'data': [{'id': 'clef-synthetic', 'task': 'classification'}]})
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            signature = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            seen[signature] += 1
            counts['attempts'] += 1
            if stage[0] == 0 and counts['attempts'] == 305:
                counts['old_504'] += 1
                return self.reply(504, {'error': {'type': 'synthetic_timeout'}})
            if stage[0] == 1:
                counts['resumed_attempts'] += 1
                if signature in old_prefix:
                    counts['prefix_replays'] += 1
                if counts['resumed_attempts'] in (2, 3, 20, 80):
                    counts['new_504'] += 1
                    return self.reply(504, {'error': {'type': 'synthetic_timeout'}})
            criteria = payload['questions']['classificacao']['criteria']
            label = next(k for k in criteria if k.startswith('indeterminad'))
            confirmed.add(signature)
            self.reply(200, {'model': payload['model'], 'answers': {'classificacao': {
                'choice': label, 'probabilities': {k: int(k == label) for k in criteria}}}})

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    env = {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET'))}
    env.pop('HERMES_CLASSIFIER_API_BASE', None); env.pop('HERMES_CLASSIFIER_KEY_FILE', None)
    command = [sys.executable, '-B', str(ROOT / 'cli.py'), 'private-analyze',
               '--input', str(source), '--tenant', 'synthetic-proof', '--work', str(root / 'exports'),
               '--timezone', 'UTC', '--cutoff', '2024-02-01', '--model', 'clef-synthetic',
               '--key-file', str(key), '--base-url', f'http://127.0.0.1:{server.server_port}/v1', '--allow-relay']
    started = time.monotonic()
    try:
        first = subprocess.run(command, capture_output=True, env=env, timeout=1200)
        assert first.returncode == 1, first.stderr.decode()[-500:]
        state = root / 'exports.checkpoint' / 'state.json'
        before = json.loads(state.read_text())
        known = [dict(row) for row in before['segments'] if row['status'] == 'ok']
        assert len(known) == 304
        assert sum(r['status'] == 'unknown' for r in before['segments']) == 1
        old_prefix.update(confirmed); stage[0] = 1
        second = subprocess.run(command + ['--resume', '--retry-transient', '--recover-uncertain', '--retry-backoff', '0'],
                                capture_output=True, env=env, timeout=1200)
        assert second.returncode == 0, second.stderr.decode()[-500:]
        report = json.loads((root / 'exports' / 'report.json').read_text())
        planned = args.events * 4
        assert report['planned_classifier_calls'] == planned
        assert report['confirmed_classifier_calls'] == planned
        assert report['unknown_classifier_calls'] == report['pending_classifier_calls'] == 0
        assert report['complete'] is True and report['pause_reason'] is None
        assert counts['prefix_replays'] == 0
        assert len(confirmed) == planned
        assert report['recovery']['errors']['http_504'] == 4
        assert counts['resumed_attempts'] == planned - 304 + 4
        assert state.exists() is False
        before_third = counts['attempts']
        third = subprocess.run(command + ['--resume', '--retry-transient'], capture_output=True, env=env, timeout=30)
        assert third.returncode == 0, third.stderr.decode()[-500:]
        assert counts['attempts'] == before_third
        assert json.loads(third.stdout)['network_used'] is False
        for path in list((root / 'exports').iterdir()) + list((root / 'exports.checkpoint').iterdir()):
            if path.is_file():
                raw = path.read_bytes()
                for forbidden in (b'SYNTHETIC-TEXT-NOT-REAL-HISTORY', b'SYNTHETIC-EVENT-', b'synthetic-only-not-a-credential'):
                    assert forbidden not in raw
        result = {'synthetic_only': True, 'planned': planned, 'confirmed': planned,
                  'old_confirmed_preserved': 304, 'prefix_replays': counts['prefix_replays'],
                  'injected_504s': counts['old_504'] + counts['new_504'],
                  'resumed_attempts': counts['resumed_attempts'], 'complete': True,
                  'completed_resume_new_calls': counts['attempts'] - before_third,
                  'privacy_sentinel_scan': 'passed', 'elapsed_s': round(time.monotonic() - started, 3),
                  'source_hashes': {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                     for name in ('cli.py', 'private_checkpoint.py', 'private_pipeline.py', 'api_client.py')}}
        (root / 'proof.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result))
    finally:
        server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()
