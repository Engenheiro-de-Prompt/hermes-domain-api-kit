"""Synthetic in-memory transport contracts; no sockets, profiles or real keys."""
import json
import unittest
from unittest.mock import patch

from api_client import ClientError, RelayClient


class PersistentRecoveryTests(unittest.TestCase):
    def test_documented_persistent_handoff_with_synthetic_profile_and_no_network(self):
        import contextlib
        import io
        from pathlib import Path
        import shlex
        import sqlite3
        import tempfile
        import cli

        class SyntheticClient:
            base_url = cli.DEFAULT_API_BASE_URL
            calls = 0

            def models(self):
                return {'data': [{'id': 'clef-flash-9b-q4-k-m', 'task': 'classification'}]}

            def classify(self, model, state, questions):
                self.calls += 1
                criteria = questions['classificacao']['criteria']
                label = next(iter(criteria))
                return {'model': model, 'answers': {'classificacao': {
                    'choice': label, 'probabilities': {k: int(k == label) for k in criteria}}}}

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            home = root / 'home'
            home.mkdir()
            with contextlib.closing(sqlite3.connect(home / 'state.db')) as db, db:
                db.executescript('CREATE TABLE sessions(id TEXT,source TEXT);'
                                 'CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
                db.execute('INSERT INTO sessions VALUES (?,?)', ('synthetic', 'cli'))
                db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', [
                    (1, 'synthetic', 'assistant', 'Resposta sintética.', 1794000000),
                    (2, 'synthetic', 'user', 'Pedido sintético.', 1794000010)])
            domain, feedback, quality = [root / name for name in ('domain', 'feedback', 'quality')]
            client = SyntheticClient()
            def invoke(args):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    return cli.main(args)
            self.assertEqual(invoke(['extract-selected', '--rubric', 'domain', '--sources', 'tasks', 'skills', 'memories',
                                     '--home', str(home), '--work', str(domain)]), 0)
            domain_args = ['analyze', '--rubric', 'domain', '--work', str(domain), '--allow-relay']
            feedback_args = ['feedback-all', '--home', str(home), '--work', str(feedback), '--timezone', 'UTC',
                             '--cutoff', '2026-11-22', '--allow-relay']
            with patch('cli.configured_client', return_value=client):
                self.assertEqual(invoke(domain_args), 0)
                self.assertEqual(invoke(feedback_args), 0)
            source = root / 'quality-input.json'
            doc = (Path(__file__).resolve().parents[1] / 'docs/THROUGHPUT_RECOVERY.md').read_text()
            line = next(line for line in doc.splitlines() if line.startswith('python3 -B -c '))
            code = shlex.split(line.rstrip('\\').strip())[3]
            with patch('sys.argv', ['prepare', str(feedback / 'corpus.json'), str(source)]):
                exec(compile(code, '<documented-offline-adapter>', 'exec'), {})
            quality_args = ['quality-analyze', '--input', str(source), '--tenant', 'selected_profile',
                            '--work', str(quality), '--max-classifier-calls', '100', '--allow-relay']
            with patch('cli.configured_client', return_value=client):
                self.assertEqual(invoke(quality_args), 0)
                completed = client.calls
                for args in (domain_args, feedback_args, quality_args):
                    self.assertEqual(invoke(args), 0)
                self.assertEqual(client.calls, completed)
            for path in (domain / 'analysis/summary.json', feedback / 'unique/dashboard.html',
                         quality / 'quality/report.json'):
                self.assertTrue(path.is_file())
            # Both independent quality rubrics remain planned; outcome has no eligible
            # assistant delivery in this profile adapter, as in private profile mode.
            report = json.loads((quality / 'quality/report.json').read_text())
            self.assertEqual(report['classifier']['eligible_event_labels'], 1)

    def test_completed_and_uncertain_attempts_are_not_replayed(self):
        import tempfile
        from pathlib import Path
        import analysis

        class SyntheticClient:
            base_url = 'https://synthetic.invalid/v1'

            def __init__(self, failure=None):
                self.calls = []
                self.failure = failure

            def classify(self, model, state, questions):
                self.calls.append(json.loads(state)['texto'])
                if len(self.calls) == 2 and self.failure is not None:
                    raise self.failure
                criteria = questions['classificacao']['criteria']
                return {'model': model, 'answers': {'classificacao': {
                    'choice': 'neutro', 'probabilities': {k: int(k == 'neutro') for k in criteria}}}}

        items = [{'id': str(i), 'kind': 'feedback', 'text': 'synthetic-' + str(i)} for i in range(3)]
        for failure in (ClientError('http_503'), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'analysis'
                client = SyntheticClient(failure)
                if isinstance(failure, KeyboardInterrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        analysis.classify(items, client, 'synthetic', output, rubric='feedback')
                    self.assertEqual(len(client.calls), 2)
                else:
                    result = analysis.classify(items, client, 'synthetic', output, rubric='feedback')
                    self.assertEqual(result['failed'], 1)
                resumed = SyntheticClient()
                result = analysis.classify(items, resumed, 'synthetic', output, rubric='feedback')
                self.assertEqual(result['failed'], 1)
                self.assertEqual(resumed.calls, ['synthetic-2'] if isinstance(failure, KeyboardInterrupt) else [])
                rows = [json.loads(line) for line in (output / 'results.jsonl').read_text().splitlines()]
                self.assertEqual(rows[0]['label'], 'neutro')
                self.assertEqual(rows[0]['status'], 'ok')
                self.assertEqual(rows[1]['status'], 'error')
                preserved = (output / 'results.jsonl').read_bytes()
                again = SyntheticClient()
                analysis.classify(items, again, 'synthetic', output, rubric='feedback')
                self.assertEqual(again.calls, [])
                self.assertEqual((output / 'results.jsonl').read_bytes(), preserved)


class BatchRetentionTests(unittest.TestCase):
    def test_post_503_is_uncertain_and_sticky_without_retry(self):
        import socket
        from unittest.mock import MagicMock
        response = MagicMock(status=503)
        connection = MagicMock()
        connection.getresponse.return_value = response
        address = [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 1))]
        client = RelayClient('http://127.0.0.1:1/v1', 'synthetic-client', require_privacy=True)
        with patch('api_client.socket.getaddrinfo', return_value=address) as dns, \
                patch('api_client.socket.socket'), \
                patch('api_client.http.client.HTTPConnection', return_value=connection):
            for _ in range(2):
                with self.assertRaisesRegex(ClientError, '^http_503$'):
                    client.classify('synthetic-model', 'synthetic-state', {})
        self.assertEqual(dns.call_count, 1)
        self.assertEqual(connection.request.call_count, 1)
        self.assertEqual(connection.request.call_args.args[:2], ('POST', '/v1/classifications'))
        response.read.assert_not_called()

    def test_explicit_keep_alive_seconds_are_preserved_and_invalid_types_rejected(self):
        for value in (-1, 0, 300):
            client = RelayClient('https://synthetic.invalid/v1', 'synthetic-client', keep_alive=value)
            with patch.object(client, '_request', return_value={}) as request:
                client.classify('synthetic-model', 'synthetic-state', {})
            self.assertEqual(json.loads(request.call_args.args[2])['keep_alive'], value)
        for value in (True, -2, '0', 1.5):
            with self.assertRaisesRegex(ClientError, '^invalid_keep_alive$'):
                RelayClient('https://synthetic.invalid/v1', 'synthetic-client', keep_alive=value)

    def test_explicit_cli_keep_alive_zero_reaches_each_classification(self):
        import cli
        args = cli.parser().parse_args(['private-analyze', '--keep-alive', '0'])
        with patch.dict('os.environ', {'HERMES_CLASSIFIER_API_KEY': 'synthetic-client'}, clear=True):
            client = cli.configured_client(args)
        with patch.object(client, '_request', return_value={}) as request:
            client.classify('synthetic-model', 'synthetic-state', {})
            client.classify('synthetic-model', 'synthetic-state', {})
        self.assertEqual([json.loads(call.args[2])['keep_alive']
                          for call in request.call_args_list], [0, 0])

    def test_batch_classification_does_not_request_unload_by_default(self):
        client = RelayClient('https://synthetic.invalid/v1', 'synthetic-client')
        with patch.object(client, '_request', return_value={}) as request:
            client.classify('synthetic-model', 'synthetic-state', {})
            client.classify('synthetic-model', 'synthetic-state', {})
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            body = json.loads(call.args[2])
            self.assertNotIn('keep_alive', body)
            self.assertEqual(set(body), {'model', 'state', 'questions'})
