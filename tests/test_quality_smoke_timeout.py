"""A fixture stall must expire inside, not kill the smoke subprocess."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from test_quality_smoke import smoke_command


class SmokeTimeoutTests(unittest.TestCase):
    def test_stalled_first_response_is_exported_and_never_replayed(self):
        calls = []
        stalled = threading.Event()
        release = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def reply(self, data):
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                self.reply({'data': [{'id': 'clef-flash-9b-q4-k-m', 'task': 'classification'}]})

            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(data)
                if len(calls) == 1:
                    stalled.set()
                    release.wait(5)
                    return
                criteria = data['questions']['classificacao']['criteria']
                label = 'resolvida_com_evidencia' if 'resolvida_com_evidencia' in criteria else 'sim'
                self.reply({'model': data['model'], 'answers': {'classificacao': {
                    'choice': label, 'probabilities': {k: float(k == label) for k in criteria}}}})

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td).resolve()
                key = root / 'key'
                key.write_text('synthetic-only')
                key.chmod(0o600)
                work = root / 'campaign'
                command = smoke_command(work, key, server.server_port)
                env = dict(os.environ)
                env.pop('HERMES_CLASSIFIER_API_KEY', None)
                # Deliberately shorter than the old 30s watchdog, not extended.
                first = subprocess.run(command, capture_output=True, text=True, env=env, timeout=3)
                self.assertTrue(stalled.is_set())
                self.assertEqual(first.returncode, 1, first.stderr)
                result = json.loads(first.stdout)
                self.assertEqual(result['total'], 7)
                self.assertEqual(result['failed'], 1)
                self.assertEqual(result['missing'], 0)
                self.assertLess(result['matched'], 7)
                self.assertEqual(len(calls), 7)
                output = work / 'quality'
                exported = json.loads((output / 'smoke-result.json').read_text())
                failed = [check for check in exported['checks'] if check['failed']]
                self.assertEqual(len(failed), 1)
                self.assertEqual(failed[0]['observed'], 'indeterminado')
                self.assertFalse(failed[0]['matched'])
                labels = json.loads((output / 'labels.json').read_text())['labels']
                self.assertEqual(sum(label['unknown_reason'] == 'classification_failed' for label in labels), 1)
                before = {p.name: p.read_bytes() for p in output.iterdir() if p.suffix in ('.json', '.jsonl', '.html')}
                again = subprocess.run(command, capture_output=True, text=True, env=env, timeout=3)
                self.assertEqual(again.returncode, 1, again.stderr)
                self.assertEqual(json.loads(again.stdout), result)
                self.assertEqual(len(calls), 7)
                self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir() if p.suffix in ('.json', '.jsonl', '.html')})
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
