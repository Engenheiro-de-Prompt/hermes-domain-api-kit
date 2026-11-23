"""Synthetic offline end-to-end recovery. No sockets, history or real keys."""
import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import cli
from api_client import ClientError


class PrivateResumeTests(unittest.TestCase):
    def source(self, root):
        source = root / 'input.json'
        source.write_text(json.dumps({'schema_version': 1, 'events': [
            {'event_id': 'PRIVATE-ID-' + str(i), 'tenant_id': 'synthetic',
             'source_id': 'PRIVATE-SOURCE', 'session_id': 'PRIVATE-SESSION',
             'event_type': 'request', 'timestamp': 1704067200 + i,
             'actor': 'user', 'source_complete': False, 'task_id': 'PRIVATE-TASK-' + str(i), 'text': 'PRIVATE-TEXT-SENTINEL ' + str(i)} for i in range(3)]}))
        return source

    def invoke(self, source, work, client, extra=()):
        args = ['private-analyze', '--input', str(source), '--tenant', 'synthetic',
                '--work', str(work), '--timezone', 'UTC', '--cutoff', '2024-02-01',
                '--model', 'clef-synthetic', '--allow-relay'] + list(extra)
        out, err = io.StringIO(), io.StringIO()
        with patch('cli.configured_client', return_value=client), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return cli.main(args), out, err

    def client(self, fail_at=None):
        class Fake:
            privacy_failure = None
            calls = 0
            def models(self):
                return {'data': [{'id': 'clef-synthetic', 'task': 'classification'}]}
            def classify(self, model, state, questions):
                self.calls += 1
                if self.calls == fail_at:
                    raise ClientError('http_429')
                criteria = questions['classificacao']['criteria']
                label = next(k for k in criteria if k.startswith('indeterminad'))
                return {'model': model, 'answers': {'classificacao': {'choice': label,
                    'probabilities': {k: int(k == label) for k in criteria}}}}
        return Fake()

    def test_confirmed_prefix_survives_429_and_uncertain_attempt_never_replays(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            first = self.client(fail_at=3)
            rc, _, _ = self.invoke(source, work, first)
            self.assertEqual(first.calls, 3, 'must pause immediately, not sweep the rest')
            self.assertEqual(rc, 1)
            checkpoint = root / 'exports.checkpoint' / 'state.json'
            data = json.loads(checkpoint.read_text())
            self.assertEqual(sum(r['status'] == 'ok' for r in data['segments']), 2)
            self.assertEqual(sum(r['status'] == 'unknown' for r in data['segments']), 1)
            second = self.client()
            rc, _, _ = self.invoke(source, work, second, ['--resume'])
            self.assertEqual(rc, 1)
            self.assertEqual(second.calls, 0)
            report = json.loads((work / 'report.json').read_text())
            self.assertFalse(report['complete'])
            self.assertEqual(report['confirmed_classifier_calls'], 2)
            self.assertEqual(report['unknown_classifier_calls'], 1)
            self.assertEqual(report['pending_classifier_calls'], report['planned_classifier_calls'] - 3)
            for name, counts in report['rubrics'].items():
                self.assertEqual(sum(counts['distribution'].values()), counts['items'] - counts['failed'], name)
            self.assertEqual(report['quality']['classifier']['distribution'], {})
            for name in ('dashboard.html', 'feedback.html'):
                html = (work / name).read_text()
                self.assertIn('PARCIAL', html)
                for rubric in report['rubrics']:
                    self.assertIn(rubric, html)
            for path in list(work.iterdir()) + list(checkpoint.parent.iterdir()):
                self.assertFalse(any(s in path.read_text() for s in ('PRIVATE-ID', 'PRIVATE-TEXT', 'PRIVATE-SOURCE', 'PRIVATE-SESSION')))

    def test_completed_resume_requires_no_key_and_prevents_replay_even_if_export_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            first = self.client()
            self.assertEqual(self.invoke(source, work, first)[0], 0)
            self.assertFalse((root / 'exports.checkpoint' / 'state.json').exists())
            self.assertTrue((root / 'exports.checkpoint' / 'completed.json').exists())
            with patch('cli.configured_client', side_effect=AssertionError('key forbidden')) as configured:
                # invoke patches client itself, so call main directly here.
                arguments = ['private-analyze', '--input', str(source), '--tenant', 'synthetic', '--work', str(work), '--timezone', 'UTC', '--cutoff', '2024-02-01', '--model', 'clef-synthetic', '--allow-relay', '--resume']
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(arguments), 0)
                    report = work / 'report.json'
                    original = report.read_bytes()
                    report.write_text('{}')
                    self.assertEqual(cli.main(arguments), 2)
                    report.write_bytes(original)
                    (work / 'report.json').unlink()
                    self.assertEqual(cli.main(arguments), 2)
                configured.assert_not_called()

    def test_contract_changes_rejected_before_client_and_preserve_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            self.invoke(source, work, self.client(3))
            state = root / 'exports.checkpoint' / 'state.json'
            before = state.read_bytes()
            for extra in (['--model', 'different'], ['--cutoff', '2024-02-02'], ['--base-url', 'https://example.invalid/v1'], ['--context-chars', '1199']):
                client = self.client()
                rc, _, _ = self.invoke(source, work, client, ['--resume'] + extra)
                self.assertEqual(rc, 2)
                self.assertEqual(client.calls, 0)
                self.assertEqual(state.read_bytes(), before)
            source.write_text(source.read_text() + ' ')
            rc, _, _ = self.invoke(source, work, self.client(), ['--resume'])
            self.assertEqual(rc, 2)
            self.assertEqual(state.read_bytes(), before)

    def test_sigkill_after_confirmed_response_then_restart_does_not_replay_prefix(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            code = '''
import sys, os, signal
sys.path.insert(0, 'tests')
from test_private_resume import PrivateResumeTests, Path
import private_checkpoint
original = private_checkpoint.Journal.save
def save(self):
    original(self)
    if sum(r['status'] == 'ok' for r in self.data['segments']) == 2:
        os.kill(os.getpid(), signal.SIGKILL)
private_checkpoint.Journal.save = save
t = PrivateResumeTests()
t.invoke(Path(sys.argv[1]), Path(sys.argv[2]), t.client())
'''
            if os.name != 'posix':
                self.skipTest('SIGKILL proof requires POSIX')
            result = subprocess.run([sys.executable, '-B', '-c', code, str(source), str(work)], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                    env={k: v for k, v in os.environ.items() if not any(s in k.upper() for s in ('KEY', 'TOKEN', 'SECRET'))}, timeout=20)
            self.assertEqual(result.returncode, -9)
            state = root / 'exports.checkpoint' / 'state.json'
            saved = json.loads(state.read_text())
            self.assertEqual(sum(r['status'] == 'ok' for r in saved['segments']), 2)
            second = self.client()
            self.assertEqual(self.invoke(source, work, second, ['--resume'])[0], 0)
            report = json.loads((work / 'report.json').read_text())
            self.assertEqual(second.calls, report['planned_classifier_calls'] - 2)
            self.assertEqual(set(report['rubrics']), {'domain', 'satisfaction', 'corrections', 'quality_correction', 'quality_outcome'})

    def test_profile_raw_selected_identity_rejects_redacted_change_before_key(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); home = root / 'profile'; home.mkdir(); work = root / 'exports'
            with contextlib.closing(sqlite3.connect(home / 'state.db')) as db, db:
                db.executescript('CREATE TABLE sessions(id TEXT,source TEXT,title TEXT);CREATE TABLE messages(id INTEGER,session_id TEXT,role TEXT,content TEXT,timestamp REAL);')
                db.execute('INSERT INTO sessions VALUES (?,?,?)', ('synthetic', 'cli', 'title'))
                db.executemany('INSERT INTO messages VALUES (?,?,?,?,?)', [(i, 'synthetic', 'user', 'password=synthetic-value-A', 1704067200 + i) for i in range(1, 4)])
            args = ['private-analyze', '--home', str(home), '--sources', 'feedback', '--work', str(work), '--timezone', 'UTC', '--cutoff', '2024-02-01', '--model', 'clef-synthetic', '--allow-relay']
            with patch('cli.configured_client', return_value=self.client(2)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args), 1)
            with contextlib.closing(sqlite3.connect(home / 'state.db')) as db, db:
                db.execute('UPDATE messages SET content=?', ('password=synthetic-value-B',))
            with patch('cli.configured_client', side_effect=AssertionError('key forbidden')) as configured, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args + ['--resume']), 2)
                configured.assert_not_called()

    def test_invalid_cached_enum_fails_before_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            self.invoke(source, work, self.client(3))
            state = root / 'exports.checkpoint' / 'state.json'
            data = json.loads(state.read_text())
            data['segments'][0]['label'] = 'invalid-enum'
            for row in data['segments']:
                if row['status'] == 'unknown': row['status'] = 'pending'
            state.write_text(json.dumps(data))
            args = ['private-analyze', '--input', str(source), '--tenant', 'synthetic', '--work', str(work), '--timezone', 'UTC', '--cutoff', '2024-02-01', '--model', 'clef-synthetic', '--allow-relay', '--resume']
            with patch('cli.configured_client', side_effect=AssertionError('must not read key')) as configured, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args), 2)
                configured.assert_not_called()

    def test_publication_gate_rejects_private_checkpoint_artifacts(self):
        from tools.check_publication import inspect
        for name in ('state.json', 'completed.json'):
            self.assertIn((0, 'private_artifact_name'), inspect(name, b'{}'))

    def test_final_confirmation_before_export_crash_is_rebuilt_without_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = self.source(root); work = root / 'exports'
            with patch('private_pipeline._save', side_effect=OSError('synthetic disk failure')):
                self.assertEqual(self.invoke(source, work, self.client())[0], 2)
            args = ['private-analyze', '--input', str(source), '--tenant', 'synthetic', '--work', str(work), '--timezone', 'UTC', '--cutoff', '2024-02-01', '--model', 'clef-synthetic', '--allow-relay', '--resume']
            with patch('cli.configured_client', side_effect=AssertionError('must not read key')) as configured, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args), 0)
                configured.assert_not_called()
