"""Offline contracts; synthetic inputs only, no model or service."""
import csv
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import analysis
import study


class RubricTests(unittest.TestCase):
    def test_builtin_contract(self):
        domain = analysis.load_rubric('domain')
        self.assertEqual(domain['criteria'], study.CRITERIA)
        feedback = analysis.load_rubric('feedback')
        self.assertEqual(feedback['aggregation'], 'unanimous')
        self.assertEqual(set(feedback['criteria']), {'correcao_redirecionamento', 'insatisfacao', 'confirmacao_positiva', 'neutro', 'indeterminado'})
        self.assertEqual(feedback['kinds'], ['feedback'])


    def test_rejects_oversized_in_memory_rubric_before_call(self):
        rubric = analysis.load_rubric('feedback')
        rubric['criteria'] = {'label_' + str(i): 'x' * 4000 for i in range(32)}
        rubric['unknown'] = 'label_0'
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, '^invalid_rubric$'):
                analysis.classify([], Client(), 'synthetic', temporary, rubric=rubric)

    def test_rejects_invalid_schemas_without_echo(self):
        valid = analysis.load_rubric('feedback')
        mutations = [dict(valid, unexpected='synthetic-private-marker'), dict(valid, id='../private'),
                     dict(valid, version=True), dict(valid, kinds=['unknown']), dict(valid, unknown='missing'),
                     dict(valid, aggregation='other'), dict(valid, criteria={'only': 'x'}),
                     dict(valid, instructions=''), dict(valid, kinds=['feedback', 'feedback'])]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'custom.json'
            for index, data in enumerate(mutations):
                with self.subTest(index=index):
                    path.write_text(json.dumps(data), encoding='utf-8')
                    with self.assertRaisesRegex(ValueError, '^invalid_rubric$'):
                        analysis.load_rubric(path)
            path.write_text('{"id":"one","id":"two"}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '^invalid_rubric$'):
                analysis.load_rubric(path)


class Client:
    base_url = 'https://synthetic.invalid/api'

    def __init__(self, labels=None):
        self.calls = []
        self.labels = iter(labels or [])

    def classify(self, model, state, questions):
        self.calls.append((model, json.loads(state), questions))
        label = next(self.labels, 'neutro')
        criteria = questions['classificacao']['criteria']
        return {'model': model, 'answers': {'classificacao': {
            'choice': label, 'probabilities': {k: int(k == label) for k in criteria}}}}


class EngineTests(unittest.TestCase):
    def test_real_api_choice_metadata_is_accepted_and_validated(self):
        class TypedClient(Client):
            metadata = {'type': 'choice', 'confidence': 0.9}

            def classify(self, model, state, questions):
                response = super().classify(model, state, questions)
                response['answers']['classificacao'].update(self.metadata)
                return response

        item = {'id': 'synthetic-metadata', 'kind': 'feedback', 'text': 'Novo pedido independente.'}
        with tempfile.TemporaryDirectory() as tmp:
            result = analysis.classify([item], TypedClient(), 'synthetic', Path(tmp)/'valid', rubric=analysis.load_rubric('feedback'))
            self.assertEqual(result['completed'], 1)
            for index, metadata in enumerate(({'type': 'other'}, {'confidence': True}, {'confidence': float('nan')}, {'confidence': 1.1}, {'extra': 'unrecognized'})):
                client = TypedClient()
                client.metadata = metadata
                result = analysis.classify([item], client, 'synthetic', Path(tmp)/str(index), rubric=analysis.load_rubric('feedback'))
                self.assertEqual(result['failed'], 1)

    def test_selected_feedback_context_flags_and_provenance_reach_model(self):
        import selection
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve() / 'home'
            home.mkdir()
            with closing(sqlite3.connect(home / 'state.db')) as db, db:
                db.execute('CREATE TABLE sessions(id TEXT)')
                db.execute("INSERT INTO sessions VALUES ('s')")
                db.execute('CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT)')
                db.executemany('INSERT INTO messages VALUES (?,?,?,?)', [
                    (1, 's', 'user', 'Estou insatisfeito com a resposta.'),
                    (2, 's', 'assistant', 'Contexto anterior longo ' * 100),
                    (3, 's', 'user', 'Estou insatisfeito com a resposta.')])
            items = selection.extract_selected(home, sources=('feedback',), context_chars=12)['items']
            client = Client(['insatisfacao', 'insatisfacao'])
            summary = analysis.classify(items, client, 'synthetic', Path(temporary) / 'out', rubric='feedback')
            self.assertEqual(summary['by_category']['insatisfacao'], 2)
            for item, (_, state, questions) in zip(items, client.calls):
                self.assertIs(state['context_missing'], item['context_missing'])
                self.assertIs(state['context_truncated'], item['context_truncated'])
                self.assertEqual(state['provenance'], item['provenance'])
                instruction = questions['classificacao']['instructions']
                self.assertIn('context_missing', instruction)
                self.assertIn('context_truncated', instruction)
                self.assertIn('indeterminado', instruction)
                self.assertIn('insuficiente', instruction)
            self.assertTrue(client.calls[0][1]['context_missing'])
            self.assertTrue(client.calls[1][1]['context_truncated'])

    def test_private_outputs_without_posix_only_os_attributes(self):
        import os
        from contextlib import ExitStack
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'output'
            with ExitStack() as stack:
                for name in ('O_NOFOLLOW', 'O_NONBLOCK', 'fchmod'):
                    if hasattr(os, name):
                        stack.enter_context(patch.object(os, name))
                        delattr(os, name)
                summary = analysis.classify([], Client(), 'synthetic', output, rubric='feedback')
            self.assertEqual(summary['total_items'], 0)
            self.assertTrue((output / 'summary.json').is_file())
            original = Path(temporary) / 'original'
            original.write_text('preserve', encoding='utf-8')
            for name in ('link', 'hardlink'):
                target = Path(temporary) / name
                if name == 'link':
                    target.symlink_to(original)
                else:
                    os.link(original, target)
                with ExitStack() as stack:
                    for attribute in ('O_NOFOLLOW', 'O_NONBLOCK', 'fchmod'):
                        if hasattr(os, attribute):
                            stack.enter_context(patch.object(os, attribute))
                            delattr(os, attribute)
                    with self.assertRaisesRegex(ValueError, '^invalid_output$'):
                        analysis._private_file(target)
                self.assertEqual(original.read_text(), 'preserve')

    def test_classify_resume_context_and_private_exports(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'analysis'
            items = [{'id': 'synthetic', 'kind': 'feedback', 'text': 'novo pedido', 'context': 'resposta anterior'}]
            client = Client()
            summary = analysis.classify(items, client, 'synthetic-model', output, rubric=analysis.load_rubric('feedback'))
            self.assertEqual(summary['completed'], 1)
            self.assertEqual(summary['semantic_qualification'], 'not_established')
            self.assertEqual(client.calls[0][1]['contexto'], 'resposta anterior')
            self.assertEqual(client.calls[0][1]['texto'], 'novo pedido')
            self.assertEqual(client.calls[0][1]['tipo'], 'feedback')
            self.assertNotIn('resposta anterior', (output / 'summary.json').read_text())
            resumed = Client()
            self.assertEqual(analysis.classify(items, resumed, 'synthetic-model', output, rubric='feedback'), summary)
            self.assertEqual(resumed.calls, [])
            import os
            if os.name == 'posix':
                for path in output.iterdir():
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.stat().st_mode & 0o777, 0o700)
            # Windows privacy depends on effective ACLs, not Unix chmod bits.
            self.assertEqual(json.loads((output / 'results.jsonl').read_text())['label'], 'neutro')


    def test_long_tail_and_conservative_aggregation(self):
        text = 'a' * 4800 + 'cauda'
        for rubric, labels, expected in [('feedback', ['neutro', 'neutro', 'correcao_redirecionamento'], 'indeterminado'),
                                          ('domain', ['pessoal', 'pessoal', 'profissional'], 'misto')]:
            with self.subTest(rubric=rubric), tempfile.TemporaryDirectory() as temporary:
                client = Client(labels)
                summary = analysis.classify([{'id': 'one', 'kind': 'task' if rubric == 'domain' else 'feedback', 'text': text}], client, 'synthetic', temporary, rubric=rubric)
                self.assertEqual(''.join(call[1]['texto'] for call in client.calls), text)
                self.assertEqual(client.calls[-1][1]['segmento'], 3)
                self.assertEqual(summary['by_category'][expected], 1)

    def test_manifest_rejects_changes_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            items = [{'id': 'one', 'kind': 'feedback', 'text': 'synthetic'}]
            analysis.classify(items, Client(), 'synthetic', temporary, rubric='feedback')
            changed = analysis.load_rubric('feedback')
            changed['instructions'] += ' nova regra'
            for index, (data, model, rubric, base, chunk) in enumerate([
                    ([dict(items[0], text='different')], 'synthetic', 'feedback', Client.base_url, 2400),
                    (items, 'other', 'feedback', Client.base_url, 2400),
                    (items, 'synthetic', changed, Client.base_url, 2400),
                    (items, 'synthetic', 'feedback', 'https://other.invalid', 2400),
                    (items, 'synthetic', 'feedback', Client.base_url, 100)]):
                client = Client()
                client.base_url = base
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, '^campaign_mismatch$'):
                    analysis.classify(data, client, model, temporary, rubric=rubric, chunk_chars=chunk)
                self.assertEqual(client.calls, [])

    def test_partial_checkpoint_blocks_resume_without_replay_or_recreation(self):
        for name in ('manifest.json', 'decisions.sqlite'):
            for damage in ('missing', 'empty', 'invalid'):
                with self.subTest(file=name, damage=damage), tempfile.TemporaryDirectory() as temporary:
                    output = Path(temporary)
                    items = [{'id': 'one', 'kind': 'feedback', 'text': 'synthetic'}]
                    analysis.classify(items, Client(), 'synthetic', output, rubric='feedback')
                    path = output / name
                    if damage == 'missing':
                        path.unlink()
                    else:
                        path.write_bytes(b'' if damage == 'empty' else b'invalid synthetic checkpoint')
                    before = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
                    client = Client()
                    with self.assertRaisesRegex(ValueError, '^checkpoint_incomplete$'):
                        analysis.classify(items, client, 'synthetic', output, rubric='feedback')
                    self.assertEqual(client.calls, [])
                    after = {p.name: p.read_bytes() for p in output.iterdir() if p.is_file()}
                    self.assertEqual(before, after)

    def test_malformed_and_transport_failures_are_terminal(self):
        valid = Client(['neutro']).classify('synthetic', '{}', {'classificacao': {'criteria': analysis.load_rubric('feedback')['criteria']}})
        import copy
        responses = [None, {}, dict(valid, model='wrong')]
        for scores in [{'neutro': 1}, {k: float('nan') for k in analysis.load_rubric('feedback')['criteria']},
                       {k: True for k in analysis.load_rubric('feedback')['criteria']},
                       {k: 0 for k in analysis.load_rubric('feedback')['criteria']}]:
            value = copy.deepcopy(valid)
            value['answers']['classificacao']['probabilities'] = scores
            responses.append(value)
        value = copy.deepcopy(valid)
        value['answers']['classificacao']['choice'] = 'insatisfacao'
        responses.append(value)
        responses.append(RuntimeError('synthetic-private-error'))
        for index, response in enumerate(responses):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as temporary:
                class Broken(Client):
                    def classify(self, model, state, questions):
                        if isinstance(response, Exception):
                            raise response
                        return response
                items = [{'id': 'one', 'kind': 'feedback', 'text': 'synthetic'}]
                summary = analysis.classify(items, Broken(), 'synthetic', temporary, rubric='feedback')
                self.assertEqual(summary['failed'], 1)
                self.assertEqual(summary['completed'], 0)
                resumed = Client()
                self.assertEqual(analysis.classify(items, resumed, 'synthetic', temporary, rubric='feedback'), summary)
                self.assertEqual(resumed.calls, [])
                self.assertNotIn('synthetic-private-error', (Path(temporary) / 'results.jsonl').read_text())

    def test_interrupted_attempt_written_before_client_is_never_replayed(self):
        with tempfile.TemporaryDirectory() as temporary:
            class Interrupted(Client):
                def classify(self, model, state, questions):
                    with closing(sqlite3.connect(Path(temporary) / 'decisions.sqlite')) as db:
                        self_test.assertEqual(db.execute('SELECT state FROM decisions').fetchall(), [('started',)])
                    raise KeyboardInterrupt()
            self_test = self
            items = [{'id': 'one', 'kind': 'feedback', 'text': 'synthetic'}]
            with self.assertRaises(KeyboardInterrupt):
                analysis.classify(items, Interrupted(), 'synthetic', temporary, rubric='feedback')
            client = Client()
            summary = analysis.classify(items, client, 'synthetic', temporary, rubric='feedback')
            self.assertEqual(client.calls, [])
            self.assertEqual(summary['failed'], 1)
            row = json.loads((Path(temporary) / 'results.jsonl').read_text())
            self.assertEqual(row['chunks'][0]['status'], 'interrupted')

    def test_sqlite_lock_blocks_concurrent_campaign(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'lock.sqlite'
            with closing(sqlite3.connect(path)) as lock:
                lock.execute('BEGIN IMMEDIATE')
                client = Client()
                with self.assertRaises(sqlite3.OperationalError):
                    analysis.classify([], client, 'synthetic', temporary, rubric='feedback')
                self.assertEqual(client.calls, [])

    def test_private_outputs_reject_hardlinked_files(self):
        import os
        with tempfile.TemporaryDirectory() as temporary:
            original = Path(temporary) / 'unrelated'
            original.write_text('preserve', encoding='utf-8')
            output = Path(temporary) / 'output'
            output.mkdir()
            os.link(original, output / 'results.jsonl')
            with self.assertRaisesRegex(ValueError, '^invalid_output$'):
                analysis.classify([], Client(), 'synthetic', output, rubric='feedback')
            self.assertEqual(original.read_text(), 'preserve')

    def test_output_destination_is_frozen(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            first, copied = Path(temporary) / 'first', Path(temporary) / 'copied'
            analysis.classify([], Client(), 'synthetic', first, rubric='feedback')
            shutil.copytree(first, copied)
            with self.assertRaisesRegex(ValueError, '^campaign_mismatch$'):
                analysis.classify([], Client(), 'synthetic', copied, rubric='feedback')

    def test_item_and_chunk_limits_precede_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Client()
            for index, (items, chunk) in enumerate([
                    ([{'id': 'one', 'kind': 'feedback', 'text': 'synthetic', 'context': 'x' * 1201}], 2400),
                    ([{'id': 'one', 'kind': 'task', 'text': 'synthetic'}], 2400), ([], 0), ([], True), ([], 2401)]):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    analysis.classify(items, client, 'synthetic', temporary, rubric='feedback', chunk_chars=chunk)
            self.assertEqual(client.calls, [])

    def test_custom_rubric_and_csv_escape_every_string(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'custom.json'
            rubric = {'id': 'custom', 'version': 1, 'instructions': 'Synthetic contract.',
                      'criteria': {'yes': 'explicit', 'unknown': 'insufficient'}, 'kinds': ['task'],
                      'unknown': 'unknown', 'aggregation': 'unanimous'}
            path.write_text(json.dumps(rubric), encoding='utf-8')
            loaded = analysis.load_rubric(path)
            self.assertEqual(loaded, rubric)
            output = Path(temporary) / 'output'
            analysis.classify([{'id': '=identity', 'kind': 'task', 'text': ' \t=FORMULA()', 'context': '@context'}],
                              Client(['yes']), 'synthetic', output, rubric=loaded)
            with (output / 'dataset.csv').open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.reader(stream, delimiter=';'))
            self.assertEqual(rows[1][0], "'=identity")
            self.assertEqual(rows[1][4], "' \t=FORMULA()")
            self.assertEqual(rows[1][5], "'@context")


if __name__ == '__main__':
    unittest.main()
