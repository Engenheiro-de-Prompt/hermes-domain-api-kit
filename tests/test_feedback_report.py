"""Somente fixtures sintéticas; nenhuma leitura de perfil/histórico real."""
import csv
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='feedback-report-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def corpus(self, timestamps):
        items = [{'id': str(i), 'kind': 'feedback', 'text': 'SYNTHETIC_PRIVATE_TEXT',
                  'provenance': [{'timestamp': t, 'session_id': 'SYNTHETIC_SESSION'}]}
                 for i, t in enumerate(timestamps)]
        (self.root / 'corpus.json').write_text(json.dumps({'items': items}), encoding='utf-8')

    def results(self, name, rows):
        path = self.root / name / 'analysis' / 'results.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')

    def test_denominator_and_missing_are_not_unknown(self):
        import feedback_report as report
        self.corpus(['2026-07-06T12:00:00Z'] * 5)
        self.results('satisfaction', [
            {'id': '0', 'label': 'satisfacao', 'status': 'ok'},
            {'id': '1', 'label': 'neutro', 'status': 'ok'},
            {'id': '2', 'label': 'indeterminado', 'status': 'ok'},
            {'id': '3', 'label': 'satisfacao', 'status': 'error'}])
        data = report.build(self.root)
        self.assertEqual(set(data), {'timezone', 'weeks', 'dated_messages', 'total_messages',
                                     'totals', 'missing_timestamps'})
        s = data['weeks'][0]['satisfaction']
        self.assertEqual(s['denominator'], 5)
        self.assertEqual(s['counts']['satisfacao'], 1)
        self.assertEqual(s['rates']['satisfacao'], 0.2)
        self.assertEqual((s['ok'], s['unknown'], s['failed'], s['unprocessed']), (3, 1, 1, 1))
        self.assertTrue(s['partial'])
        self.assertIsNone(data['totals']['corrections']['counts']['correcao'])

    def test_local_calendar_gaps_and_missing_timestamps(self):
        import feedback_report as report
        self.corpus(['2026-07-06T01:00:00Z', 1784552400.5, None, 'invalid',
                     '2026-07-20T12:00:00'])
        data = report.build(self.root)
        self.assertEqual(data['timezone'], 'America/Sao_Paulo')
        self.assertEqual([w['week'] for w in data['weeks']],
                         ['2026-06-29', '2026-07-06', '2026-07-13', '2026-07-20'])
        self.assertEqual([w['messages'] for w in data['weeks']], [1, 0, 0, 2])
        self.assertEqual(data['missing_timestamps']['messages'], 2)
        self.assertIsNone(data['weeks'][1]['satisfaction']['rates']['satisfacao'])

    def test_outputs_are_aggregated_and_composite_labels_count_once(self):
        import feedback_report as report
        self.corpus(['2026-07-06T12:00:00Z'] * 3)
        self.results('corrections', [
            {'id': '0', 'label': 'ambos', 'status': 'ok'},
            {'id': '1', 'label': 'correcao', 'status': 'ok'},
            {'id': '2', 'label': 'sem_intervencao', 'status': 'ok'}])
        data = report.build(self.root)
        self.assertEqual(data['totals']['corrections']['signal_total'], 2)
        self.assertEqual(data['totals']['corrections']['signal_rate'], 2 / 3)
        self.assertEqual(json.loads((self.root / 'report.json').read_text(encoding='utf-8')), data)
        with (self.root / 'weekly.csv').open(encoding='utf-8', newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]['corrections_ambos_count'], '1')
        self.assertEqual(rows[0]['satisfaction_satisfacao_count'], '')
        for filename in ('report.json', 'weekly.csv', 'report.html'):
            text = (self.root / filename).read_text(encoding='utf-8')
            for sentinel in ('SYNTHETIC_PRIVATE_TEXT', 'SYNTHETIC_SESSION', str(self.root)):
                self.assertNotIn(sentinel, text)
        html = (self.root / 'report.html').read_text(encoding='utf-8')
        self.assertNotIn('<script', html)
        self.assertNotIn('https://', html)
        self.assertIn('PARCIAL', html)

    def test_invalid_labels_are_failures_and_other_kinds_are_excluded(self):
        import feedback_report as report
        self.corpus([None, None])
        path = self.root / 'corpus.json'
        source = json.loads(path.read_text(encoding='utf-8'))
        source['items'][1]['kind'] = 'task'
        path.write_text(json.dumps(source), encoding='utf-8')
        self.results('satisfaction', [{'id': '0', 'label': 'invalid', 'status': 'ok'}])
        data = report.build(self.root)
        self.assertEqual(data['total_messages'], 1)
        self.assertEqual(data['weeks'], [])
        self.assertEqual(data['totals']['satisfaction']['failed'], 1)
        self.assertIsNone(data['totals']['satisfaction']['signal_total'])

    def test_all_labels_are_exclusive_and_rubrics_independent(self):
        import feedback_report as report
        self.corpus(['2026-07-06T12:00:00Z'] * 5)
        for name, labels in report.LABELS.items():
            self.results(name, [{'id': str(i), 'status': 'ok', 'label': label}
                                for i, label in enumerate(labels)])
        data = report.build(self.root)
        for name in report.LABELS:
            self.assertEqual(list(data['totals'][name]['counts'].values()), [1] * 5)
            self.assertEqual(data['totals'][name]['signal_total'], 3)
            self.assertFalse(data['totals'][name]['partial'])

    def test_conflicting_repeated_result_ids_are_failures_not_last_wins(self):
        import feedback_report as report
        self.corpus(['2026-07-06T12:00:00Z'])
        self.results('satisfaction', [
            {'id': '0', 'status': 'ok', 'label': 'satisfacao'},
            {'id': '0', 'status': 'ok', 'label': 'insatisfacao'}])
        s = report.build(self.root)['totals']['satisfaction']
        self.assertEqual(s['failed'], 1)
        self.assertEqual(s['ok'], 0)
        self.assertIsNone(s['counts']['satisfacao'])

    def test_non_string_labels_are_failures_not_exceptions(self):
        import feedback_report as report
        self.corpus([None] * 4)
        self.results('satisfaction', [
            {'id': str(i), 'status': 'ok', 'label': label}
            for i, label in enumerate(([], {}, None, True))])
        summary = report.build(self.root)['totals']['satisfaction']
        self.assertEqual(summary['failed'], 4)
        self.assertEqual(summary['ok'], 0)
        self.assertIsNone(summary['counts']['satisfacao'])

    def test_empty_corpus_has_no_invented_rates(self):
        import feedback_report as report
        self.corpus([])
        data = report.build(self.root)
        self.assertEqual(data['weeks'], [])
        self.assertIsNone(data['totals']['corrections']['status_rates']['ok'])

    def test_utc_mode_needs_no_system_timezone_database_or_import_reads(self):
        import feedback_report as report
        self.corpus(['2026-07-06T01:00:00Z'])
        try:
            with patch('zoneinfo.ZoneInfo', side_effect=AssertionError('timezone file read')):
                importlib.reload(report)
                data = report.build(self.root, timezone_name='UTC')
            self.assertEqual(data['timezone'], 'UTC')
            self.assertEqual(data['weeks'][0]['week'], '2026-07-06')
        finally:
            importlib.reload(report)

    def test_import_does_not_read_inputs(self):
        import feedback_report as report
        with patch.object(Path, 'read_text', side_effect=AssertionError('import read')):
            importlib.reload(report)

    def test_cli_errors_do_not_echo_input_or_paths(self):
        import feedback_report as report
        self.corpus([None])
        command = [sys.executable, '-B', report.__file__, str(self.root)]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        (self.root / 'corpus.json').write_text('SYNTHETIC_INVALID_JSON', encoding='utf-8')
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        for sentinel in ('Traceback', str(self.root), 'SYNTHETIC_INVALID_JSON'):
            self.assertNotIn(sentinel, run.stderr)


if __name__ == '__main__':
    unittest.main()
