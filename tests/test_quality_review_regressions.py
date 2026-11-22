"""Regressões da revisão: filesystem temporário, credencial e HTTP sintéticos."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def campaign():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            requests.append('GET')
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({'data': [{'id': 'clef-flash-9b-q4-k-m', 'task': 'classification'}]}).encode())

        def do_POST(self):
            requests.append('POST')
            data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            criteria = data['questions']['classificacao']['criteria']
            label = 'resolvida_com_evidencia' if 'resolvida_com_evidencia' in criteria else 'sim'
            response = {'model': data['model'], 'answers': {'classificacao': {
                'choice': label, 'probabilities': {k: float(k == label) for k in criteria}}}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as td:
            key = Path(td).resolve() / 'key'
            key.write_text('synthetic-only')
            key.chmod(0o600)
            work = Path(td).resolve() / 'campaign'
            env = dict(os.environ)
            env.pop('HERMES_CLASSIFIER_API_KEY', None)

            def invoke(command='quality-smoke'):
                args = [sys.executable, '-B', str(ROOT / 'cli.py'), command,
                        '--work', str(work), '--base-url', f'http://127.0.0.1:{server.server_port}/v1',
                        '--key-file', str(key), '--max-classifier-calls', '7', '--allow-relay']
                if command != 'quality-smoke':
                    args += ['--input', str(ROOT / 'examples/quality-smoke.synthetic.json'),
                             '--tenant', 'synthetic-smoke']
                return subprocess.run(args, capture_output=True, text=True, env=env, timeout=30)

            first = invoke()
            if first.returncode != 1 or requests.count('POST') != 7:
                raise AssertionError('A campanha sintética inicial não foi exercitada como esperado: ' + first.stderr)
            yield work, requests, invoke
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def snapshot(work):
    return {str(p.relative_to(work)): p.read_bytes() for p in work.rglob('*')
            if p.is_file() and p.name != 'lock.sqlite'}


class QualityReviewRegressions(unittest.TestCase):
    def test_changed_legacy_contract_blocks_without_overwriting_outputs(self):
        with campaign() as (work, requests, invoke):
            root = work / 'quality'
            manifest = json.loads((root / 'manifest.json').read_text())
            for name in ('classification_started', 'validation_controls', 'validation_controls_sha256'):
                manifest.pop(name, None)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            frozen = json.loads((work / 'smoke-manifest.json').read_text())
            frozen['expected_sha256'] = '0' * 64
            (work / 'smoke-manifest.json').write_text(json.dumps(frozen))
            before, calls = snapshot(work), list(requests)
            offline = invoke('quality-report')
            self.assertEqual(offline.returncode, 2, offline.stderr)
            self.assertIn('campaign_mismatch', offline.stderr)
            self.assertEqual(requests, calls)
            self.assertEqual(snapshot(work), before)

    def test_changed_frozen_controls_fail_integrity_before_output(self):
        with campaign() as (work, requests, invoke):
            root = work / 'quality'
            manifest = json.loads((root / 'manifest.json').read_text())
            manifest['validation_controls']['checks'][0]['expected'] = 'indeterminada'
            (root / 'manifest.json').write_text(json.dumps(manifest))
            before, calls = snapshot(work), list(requests)
            offline = invoke('quality-report')
            self.assertEqual(offline.returncode, 2, offline.stderr)
            self.assertIn('snapshot_integrity_failed', offline.stderr)
            self.assertEqual(requests, calls)
            self.assertEqual(snapshot(work), before)

    def test_legacy_smoke_restores_only_against_original_contract_hashes(self):
        with campaign() as (work, requests, invoke):
            root = work / 'quality'
            validation = json.loads((root / 'report.json').read_text())['validation']
            manifest = json.loads((root / 'manifest.json').read_text())
            for name in ('classification_started', 'validation_controls', 'validation_controls_sha256'):
                manifest.pop(name, None)
            (root / 'manifest.json').write_text(json.dumps(manifest))
            calls = list(requests)
            offline = invoke('quality-report')
            self.assertEqual(offline.returncode, 0, offline.stderr)
            self.assertEqual(json.loads((root / 'report.json').read_text()).get('validation'), validation)
            self.assertEqual(requests, calls)

    def test_missing_smoke_contract_cannot_be_refrozen_after_start(self):
        with campaign() as (work, requests, invoke):
            (work / 'smoke-manifest.json').unlink()
            before, calls = snapshot(work), list(requests)
            resumed = invoke()
            self.assertEqual(resumed.returncode, 2, resumed.stderr)
            self.assertIn('checkpoint_incomplete', resumed.stderr)
            self.assertEqual(requests, calls)
            self.assertEqual(snapshot(work), before)
            self.assertFalse((work / 'smoke-manifest.json').exists())

    def test_offline_report_preserves_frozen_validation_without_requests(self):
        with campaign() as (work, requests, invoke):
            root = work / 'quality'
            validation = json.loads((root / 'report.json').read_text())['validation']
            responses = {str(p): p.read_bytes() for p in root.glob('classification/*/results.jsonl')}
            calls = list(requests)
            offline = invoke('quality-report')
            self.assertEqual(offline.returncode, 0, offline.stderr)
            self.assertEqual(json.loads((root / 'report.json').read_text()).get('validation'), validation)
            self.assertIn('Classificador não homologado', (root / 'dashboard.html').read_text())
            self.assertIn('7 rótulos disponíveis', (root / 'dashboard.html').read_text())
            self.assertNotIn('Classificação de texto não executada', (root / 'dashboard.html').read_text())
            self.assertEqual(requests, calls)
            self.assertEqual({str(p): p.read_bytes() for p in root.glob('classification/*/results.jsonl')}, responses)

    def test_loss_of_internal_tree_and_manifest_blocks_before_client_or_recreation(self):
        with campaign() as (work, requests, invoke):
            root = work / 'quality'
            shutil.rmtree(root / 'classification')
            (root / 'classification-manifest.json').unlink()
            before, calls = snapshot(work), list(requests)
            resumed = invoke('quality-analyze')
            self.assertEqual(resumed.returncode, 2, resumed.stderr)
            self.assertIn('checkpoint_incomplete', resumed.stderr)
            self.assertEqual(requests, calls)
            self.assertEqual(snapshot(work), before)
            self.assertFalse((root / 'classification').exists())


if __name__ == '__main__':
    unittest.main()
