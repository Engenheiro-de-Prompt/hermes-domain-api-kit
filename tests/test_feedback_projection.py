"""Deduplicação exercitada somente com eventos sintéticos temporários."""
import json
from pathlib import Path
import tempfile
import unittest


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='feedback-projection-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def item(self, ident, stamp='2026-07-06T12:00:00Z', session='SYNTHETIC_SESSION',
             text='SYNTHETIC_PRIVATE_TEXT', kind='feedback'):
        return {'id': ident, 'kind': kind, 'text': text,
                'provenance': [{'timestamp': stamp, 'session_id': session,
                                'path': 'SYNTHETIC_PRIVATE_PATH'}]}

    def corpus(self, items):
        (self.root / 'corpus.json').write_text(json.dumps({'items': items}), encoding='utf-8')

    def results(self, name, rows):
        path = self.root / name / 'analysis' / 'results.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def test_invalid_dates_do_not_merge_events(self):
        import feedback_projection as projection
        self.corpus([self.item(i, stamp='invalid-date') for i in ('a', 'b')])
        self.assertEqual(projection.project(self.root)['total_messages'], 2)

    def test_later_date_cannot_validate_an_invalid_event_identity(self):
        import feedback_projection as projection
        items = [self.item(i, stamp='invalid-date') for i in ('a', 'b')]
        for item in items:
            item['provenance'].append({'timestamp': '2026-07-06T12:00:00Z'})
        self.corpus(items)
        data = projection.project(self.root)
        self.assertEqual(data['total_messages'], 2)
        self.assertEqual(data['deduplication']['duplicate_copies_removed'], 0)

    def test_failed_copy_is_not_hidden_by_a_missing_copy(self):
        import feedback_projection as projection
        self.corpus([self.item('a'), self.item('b')])
        self.results('satisfaction', [{'id': 'a', 'status': 'error', 'label': 'satisfacao'}])
        self.results('corrections', [{'id': 'a', 'status': 'ok', 'label': 'correcao'}])
        data = projection.project(self.root)
        self.assertEqual(data['totals']['satisfaction']['failed'], 1)
        self.assertEqual(data['totals']['satisfaction']['unprocessed'], 0)
        self.assertEqual(data['totals']['corrections']['unprocessed'], 1)
        self.assertTrue(data['totals']['satisfaction']['partial'])
        self.assertIsNone(data['totals']['satisfaction']['counts']['satisfacao'])

    def test_dedup_metadata_counts_only_feedback_records(self):
        import feedback_projection as projection
        self.corpus([self.item('a'), self.item('b'), self.item('task', kind='task')])
        meta = projection.project(self.root)['deduplication']
        self.assertEqual(meta['raw_records'], 2)
        self.assertEqual(meta['unique_events'], 1)
        self.assertEqual(meta['duplicate_copies_removed'], 1)

    def test_absent_or_malformed_provenance_is_never_duplicate_evidence(self):
        import feedback_projection as projection
        variants = [[], None, [None], [{'timestamp': '2026-07-06T12:00:00Z', 'session_id': []}]]
        items = []
        for index, provenance in enumerate(variants):
            for copy in range(2):
                item = self.item(f'{index}-{copy}')
                item['provenance'] = provenance
                items.append(item)
        self.corpus(items)
        data = projection.project(self.root)
        self.assertEqual(data['total_messages'], 8)
        self.assertEqual(data['deduplication']['duplicate_copies_removed'], 0)

    def test_repeated_conflicting_result_rows_do_not_select_last_label(self):
        import feedback_projection as projection
        self.corpus([self.item('a')])
        self.results('satisfaction', [
            {'id': 'a', 'status': 'ok', 'label': 'satisfacao'},
            {'id': 'a', 'status': 'ok', 'label': 'insatisfacao'}])
        data = projection.project(self.root)
        self.assertEqual(data['totals']['satisfaction']['failed'], 1)
        self.assertEqual(data['totals']['satisfaction']['ok'], 0)

    def test_utc_projection_is_portable_without_timezone_database(self):
        from unittest.mock import patch
        import feedback_projection as projection
        self.corpus([self.item('a', stamp='2026-07-06T01:00:00Z')])
        with patch.object(projection.report, 'ZoneInfo', side_effect=AssertionError('timezone read')):
            data = projection.project(self.root, timezone_name='UTC')
        self.assertEqual(data['timezone'], 'UTC')
        self.assertEqual(data['weeks'][0]['week'], '2026-07-06')

    def test_projection_does_not_copy_private_provenance_or_controls(self):
        import feedback_projection as projection
        self.corpus([self.item('a'), self.item('b')])
        (self.root / 'controls.json').write_text('SYNTHETIC_PRIVATE_CONTROL', encoding='utf-8')
        projection.project(self.root)
        self.assertFalse((self.root / 'unique' / 'controls.json').exists())
        for path in (self.root / 'unique').rglob('*'):
            if path.is_file():
                text = path.read_text(encoding='utf-8')
                for sentinel in ('SYNTHETIC_SESSION', 'SYNTHETIC_PRIVATE_PATH',
                                 'SYNTHETIC_PRIVATE_TEXT', 'SYNTHETIC_PRIVATE_CONTROL'):
                    self.assertNotIn(sentinel, text)
        corpus = json.loads((self.root / 'unique' / 'corpus.json').read_text(encoding='utf-8'))
        self.assertEqual(corpus['items'][0]['provenance'],
                         [{'timestamp': '2026-07-06T12:00:00Z'}])

    def test_event_copies_count_once_and_disagreements_abstain(self):
        import feedback_projection as projection
        self.corpus([self.item('a'), self.item('b'),
                     self.item('c', stamp='2026-07-13T12:00:00Z')])
        for name, labels in [('satisfaction', ('satisfacao', 'insatisfacao', 'neutro')),
                             ('corrections', ('correcao', 'correcao', 'sem_intervencao'))]:
            self.results(name, [{'id': ident, 'status': 'ok', 'label': label}
                                for ident, label in zip(('a', 'b', 'c'), labels)])
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file()}
        data = projection.project(self.root)
        self.assertEqual(data['total_messages'], 2)
        self.assertEqual(data['totals']['satisfaction']['counts']['indeterminado'], 1)
        self.assertEqual(data['totals']['corrections']['counts']['correcao'], 1)
        self.assertEqual(data['deduplication']['duplicate_copies_removed'], 1)
        self.assertEqual(data['deduplication']['duplicate_label_disagreements'],
                         {'satisfaction': 1, 'corrections': 0})
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        self.assertNotIn('SYNTHETIC_PRIVATE_TEXT',
                         (self.root / 'unique' / 'corpus.json').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
