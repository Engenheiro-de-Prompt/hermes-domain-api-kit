"""CLI de verificação exploratória com transporte explicitamente sintético."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]


class SmokeTests(unittest.TestCase):
    def test_smoke_exports_disagreement_and_resumes_without_replaying(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({'data': [{'id': 'clef-flash-9b-q4-k-m', 'task': 'classification'}]}).encode())
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                calls.append(data)
                criteria = data['questions']['classificacao']['criteria']
                label = 'resolvida_com_evidencia' if 'resolvida_com_evidencia' in criteria else 'sim'
                response = {'model': data['model'], 'answers': {'classificacao': {
                    'choice': label, 'probabilities': {k: float(k == label) for k in criteria}}}}
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(response).encode())
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                key = Path(td) / 'key'; key.write_text('synthetic-only'); key.chmod(0o600)
                work = Path(td) / 'campaign'
                command = [sys.executable, '-B', str(ROOT / 'cli.py'), 'quality-smoke',
                    '--work', str(work), '--base-url', f'http://127.0.0.1:{server.server_port}/v1',
                    '--key-file', str(key), '--max-classifier-calls', '7', '--allow-relay']
                env = dict(os.environ); env.pop('HERMES_CLASSIFIER_API_KEY', None)
                first = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(first.returncode, 1, first.stderr)
                result = json.loads(first.stdout)
                self.assertEqual(result['total'], 7)
                self.assertLess(result['matched'], 7)
                self.assertEqual(result['failed'], 0)
                self.assertEqual(result['qualification'], 'exploratory_synthetic_controls')
                output = work / 'quality'
                self.assertTrue((output / 'smoke-result.json').is_file())
                self.assertIn('Controles sintéticos', (output / 'dashboard.html').read_text())
                self.assertIn('Classificador não homologado', (output / 'dashboard.html').read_text())
                self.assertIn('DADOS SINTÉTICOS', (output / 'dashboard.html').read_text())
                self.assertEqual(len(calls), 7)
                before = (output / 'dashboard.html').read_bytes()
                again = subprocess.run(command, capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(again.returncode, 1, again.stderr)
                self.assertEqual(len(calls), 7)
                self.assertEqual(before, (output / 'dashboard.html').read_bytes())
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
