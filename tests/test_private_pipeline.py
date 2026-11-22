import contextlib
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import cli


class PrivatePipelineTests(unittest.TestCase):
    def run_cli(self, arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = cli.main(arguments)
            except SystemExit as error:
                rc = error.code
        return rc, out.getvalue(), err.getvalue()

    def source(self, root):
        source = root / 'events.json'
        events = []
        for i, stamp in enumerate((1704067200, 1705276800)):
            events.append({'event_id': 'private-event-' + str(i), 'tenant_id': 'private-tenant',
                           'source_id': 'private-source', 'session_id': 'private-session',
                           'task_id': 'private-task-' + str(i), 'event_type': 'request',
                           'timestamp': stamp, 'actor': 'user', 'source_complete': False,
                           'text': 'PRIVATE-CONTENT-SENTINEL preciso de ajuda',
                           'workflow': 'PRIVATE-WORKFLOW-SENTINEL'})
        source.write_text(json.dumps({'schema_version': 1, 'events': events}))
        return source

    def test_synthetic_profile_plans_without_changing_history_or_copying_text(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / 'selected-profile'; home.mkdir()
            db = sqlite3.connect(home / 'state.db')
            db.executescript('CREATE TABLE sessions(id TEXT,source TEXT,title TEXT);CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
            db.execute('INSERT INTO sessions VALUES (?,?,?)', ('synthetic', 'cli', 'PRIVATE-PROFILE-TITLE'))
            db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', [(1, 'synthetic', 'assistant', 'PRIVATE-ASSISTANT-TEXT', 1), (2, 'synthetic', 'user', 'PRIVATE-USER-TEXT', 2)])
            db.commit(); db.close()
            before = (home / 'state.db').read_bytes()
            output = root / 'output'
            with patch('cli.configured_client', side_effect=AssertionError('network_or_key_forbidden')):
                rc, out, err = self.run_cli(['private-analyze', '--home', str(home), '--sources', 'tasks', 'feedback', '--work', str(output), '--dry-run', '--timezone', 'UTC'])
            self.assertEqual(rc, 0, err)
            self.assertGreater(json.loads(out)['estimated_classifier_calls'], 0)
            self.assertEqual((home / 'state.db').read_bytes(), before)
            self.assertFalse(output.exists())
            for value in ('PRIVATE-PROFILE-TITLE', 'PRIVATE-ASSISTANT-TEXT', 'PRIVATE-USER-TEXT', str(home)):
                self.assertNotIn(value, out + err)

    def test_private_dry_run_is_metadata_only_even_over_budget(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source, output = self.source(root), root / 'output'
            with patch('cli.configured_client', side_effect=AssertionError('network_or_key_forbidden')):
                rc, out, err = self.run_cli(['private-analyze', '--input', str(source), '--tenant', 'private-tenant', '--work', str(output), '--dry-run', '--max-classifier-calls', '0', '--timezone', 'UTC'])
            self.assertEqual(rc, 0, err)
            plan = json.loads(out)
            self.assertGreater(plan['estimated_classifier_calls'], 0)
            self.assertFalse(plan['budget_sufficient'])
            self.assertFalse(plan['network_used'])
            self.assertFalse(output.exists())
            self.assertNotIn('PRIVATE-CONTENT', out + err)

    def test_unsupported_private_options_never_silently_send_data(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = self.source(root)
            for options in (['--resume'], ['--no-redact'], ['--max-cost', '1'], ['--max-tokens', '1']):
                with self.subTest(options=options), patch('cli.configured_client', side_effect=AssertionError('network_or_key_forbidden')):
                    rc, out, err = self.run_cli(['private-analyze', '--input', str(source), '--tenant', 'private-tenant', '--work', str(root / 'output'), '--allow-relay', '--timezone', 'UTC'] + options)
                self.assertEqual(rc, 2)
                self.assertIn('invalid_arguments', err)

    def test_public_private_smoke_fixture_validates_before_inference(self):
        from quality import normalize
        from private_pipeline import _plans
        fixture = json.loads((Path(__file__).resolve().parents[1] / 'examples/private-smoke.synthetic.json').read_text())
        events, _ = normalize(fixture['events'], 'synthetic-private-smoke')
        self.assertEqual(len(events), 2)
        import hashlib
        examples = Path(__file__).resolve().parents[1] / 'examples'
        expected = json.loads((examples / 'private-smoke.expected.synthetic.json').read_text())
        self.assertEqual(hashlib.sha256((examples / 'private-smoke.synthetic.json').read_bytes()).hexdigest(), expected['fixture_sha256'])

    def test_budget_blocks_before_client_or_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source, output = self.source(root), root / 'output'
            with patch('cli.configured_client', side_effect=AssertionError('must not read key')) as client:
                rc, out, err = self.run_cli(['private-analyze', '--input', str(source), '--tenant', 'private-tenant', '--work', str(output), '--allow-relay', '--max-classifier-calls', '0', '--timezone', 'UTC'])
            self.assertEqual(rc, 2)
            self.assertIn('classifier_budget_exceeded', err)
            client.assert_not_called()
            self.assertFalse(output.exists())
            self.assertNotIn('PRIVATE-', out + err)

    def test_real_http_pipeline_emits_only_aggregates(self):
        posts = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            def reply(self, data):
                raw = json.dumps(data).encode()
                self.send_response(200)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_GET(self):
                self.reply({'data': [{'id': 'clef-synthetic', 'task': 'classification'}]})
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                posts.append(data)
                criteria = data['questions']['classificacao']['criteria']
                label = next(x for x in criteria if x.startswith('indeterminad'))
                self.reply({'model': data['model'], 'answers': {'classificacao': {
                    'choice': label, 'probabilities': {key: int(key == label) for key in criteria}}}})
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source, output = self.source(root), root / 'output'
                key = root / 'key'
                key.write_text('synthetic-client-credential')
                key.chmod(0o600)
                before = source.read_bytes()
                with patch.dict('os.environ', {'HERMES_CLASSIFIER_API_KEY': ''}):
                    rc, out, err = self.run_cli(['private-analyze', '--input', str(source), '--tenant', 'private-tenant', '--work', str(output), '--allow-relay', '--key-file', str(key), '--base-url', f'http://127.0.0.1:{server.server_port}/v1', '--timezone', 'UTC'])
                self.assertEqual(rc, 0, err)
                self.assertGreater(len(posts), 0)
                self.assertEqual(source.read_bytes(), before)
                self.assertEqual(set(p.name for p in output.iterdir()), {'report.json', 'narrative.json', 'dashboard.html', 'feedback.html', 'privacy.json'})
                saved = '\n'.join(p.read_text() for p in output.iterdir()) + out + err
                for sentinel in ('PRIVATE-CONTENT-SENTINEL', 'PRIVATE-WORKFLOW-SENTINEL', 'private-event-', 'private-session', 'private-task-', 'private-tenant', 'private-source', str(source), 'synthetic-client-credential'):
                    self.assertNotIn(sentinel, saved)
                self.assertIn('<svg', (output / 'dashboard.html').read_text())
                self.assertIn('<svg', (output / 'feedback.html').read_text())
                self.assertNotIn('private-event-', json.dumps(posts))
                self.assertTrue(all('provenance' not in json.dumps(p['state']) for p in posts))
                report = json.loads((output / 'report.json').read_text())
                self.assertEqual(report['quality']['metrics']['first_attempt_resolution']['value'], None)
                self.assertGreaterEqual(len(report['feedback']['weeks']), 3)
                self.assertIsNotNone(report['feedback']['observed_history']['first_date'])
                self.assertIsNotNone(report['feedback']['observed_history']['last_date'])
                self.assertEqual(report['quality']['classifier']['models'], [report['analysis_contract']['model_id']])
                import os
                if os.name == 'posix':
                    for path in output.iterdir():
                        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_missing_confirmation_after_catalog_stops_all_further_posts(self):
        posts = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            def do_GET(self):
                raw = json.dumps({'data': [{'id': 'clef-synthetic', 'task': 'classification'}]}).encode()
                self.send_response(200)
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                posts.append(1)
                self.send_response(200)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp).resolve()
                source, output = self.source(root), root / 'output'
                with patch.dict('os.environ', {'HERMES_CLASSIFIER_API_KEY': 'synthetic-client'}):
                    rc, out, err = self.run_cli(['private-analyze', '--input', str(source), '--tenant', 'private-tenant', '--work', str(output), '--allow-relay', '--base-url', f'http://127.0.0.1:{server.server_port}/v1', '--timezone', 'UTC'])
                self.assertEqual(rc, 2)
                self.assertEqual(posts, [1])
                self.assertFalse(output.exists())
                self.assertIn('privacy_confirmation_missing', err)
                self.assertNotIn('PRIVATE-CONTENT', out + err)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_source_explicit_and_output_no_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            source = self.source(root)
            for extra in ([], ['--input', str(source), '--tenant', 'private-tenant', '--home', str(root)], ['--input', str(source), '--tenant', 'private-tenant', '--work', str(root)]):
                with self.subTest(extra=extra):
                    rc, out, err = self.run_cli(['private-analyze', '--allow-relay', '--timezone', 'UTC'] + extra)
                    self.assertEqual(rc, 2)
                    self.assertNotIn('PRIVATE-CONTENT', out + err)
