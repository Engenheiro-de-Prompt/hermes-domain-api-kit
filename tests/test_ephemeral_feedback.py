"""In-memory synthetic contracts; no profiles, services or temporary files."""
import copy
from datetime import date
import json
import unittest
from unittest.mock import patch

import feedback_dashboard as dashboard


def item(ident, stamp: object = '2026-07-06T12:00:00Z', session='PRIVATE_SESSION', text=None):
    return {'id': ident, 'kind': 'feedback', 'text': text or 'PRIVATE_TEXT_' + ident,
            'provenance': [{'timestamp': stamp, 'session_id': session,
                            'path': 'PRIVATE_PATH'}]}


def row(ident, label: object = 'satisfacao', status='ok'):
    return {'id': ident, 'label': label, 'status': status}


class EphemeralFeedbackTests(unittest.TestCase):
    def test_repeated_identical_rows_and_invalid_labels_keep_processing_states(self):
        from ephemeral_feedback import build
        inputs = [item(str(index)) for index in range(5)] + [item('undated', None)]
        data = build(inputs, {'satisfaction': [row('0'), row('0'), row('1', []),
                                               row('2', {}), row('3', 'indeterminado'),
                                               row('undated', 'neutro')]})
        s = data['weeks'][0]['satisfaction']
        self.assertEqual((s['ok'], s['failed'], s['unknown'], s['unprocessed']), (2, 2, 1, 1))
        self.assertEqual(s['denominator'], 5)
        self.assertEqual(data['totals']['satisfaction']['denominator'], 6)
        self.assertEqual(data['missing_timestamps']['satisfaction']['denominator'], 1)
        self.assertEqual(s['status_rates']['unknown'], 1 / 5)
        self.assertEqual(s['counts']['satisfacao'], 1)

    def test_dedup_requires_exact_full_identity_and_never_uses_later_date_as_evidence(self):
        from ephemeral_feedback import build
        base = item('a', text='PRIVATE_FULL_TEXT')
        copies = [base, item('b', text='PRIVATE_FULL_TEXT'),
                  item('c', text='PRIVATE_FULL_TEXT_MORE'),
                  item('d', session='OTHER_SESSION', text='PRIVATE_FULL_TEXT'),
                  item('e', '2026-07-06T12:00:00+00:00', text='PRIVATE_FULL_TEXT')]
        for ident in ('f', 'g'):
            candidate = item(ident, 'invalid', text='PRIVATE_FULL_TEXT')
            candidate['provenance'].append({'timestamp': '2026-07-06T12:00:00Z'})
            copies.append(candidate)
        copies += [item('same-id', None), item('same-id', None)]
        data = build(copies, {})
        self.assertEqual(data['total_messages'], 8)
        self.assertEqual(data['dated_messages'], 6)
        self.assertEqual(data['deduplication']['duplicate_copies_removed'], 1)

    def test_return_is_allowlisted_aggregate_only_without_io_or_input_mutation(self):
        from ephemeral_feedback import build
        import feedback_report
        import socket
        from pathlib import Path
        source = item('PRIVATE_ID')
        source['context'] = 'PRIVATE_CONTEXT'
        labels = {'satisfaction': [dict(row('PRIVATE_ID'), score=0.987,
                                         response='PRIVATE_RESPONSE')],
                  'private_rubric': [{'id': 'PRIVATE_ID', 'label': 'PRIVATE_LABEL'}]}
        inputs = [source, dict(item('PRIVATE_TASK'), kind='task')]
        before = copy.deepcopy((inputs, labels))
        with patch('builtins.open', side_effect=AssertionError('file access')), \
             patch.object(Path, 'open', side_effect=AssertionError('path access')), \
             patch.object(socket, 'socket', side_effect=AssertionError('network')), \
             patch.object(feedback_report, 'ZoneInfo', side_effect=AssertionError('tz read')):
            data = build(inputs, labels)
            html = dashboard.render(data, date(2026, 8, 3))
        self.assertEqual((inputs, labels), before)
        self.assertEqual(set(data), {'timezone', 'weeks', 'dated_messages', 'total_messages',
                                     'totals', 'missing_timestamps', 'deduplication'})
        summary_keys = {'counts', 'status_rates', 'signal_total', 'signal_rate', 'no_signal',
                        'rates', 'ok', 'unknown', 'failed', 'unprocessed', 'partial', 'denominator'}
        for name, labels_allowed in feedback_report.LABELS.items():
            for summary in (data['totals'][name], data['missing_timestamps'][name],
                            data['weeks'][0][name]):
                self.assertEqual(set(summary), summary_keys)
                self.assertEqual(set(summary['counts']), set(labels_allowed))
                self.assertEqual(set(summary['rates']), set(labels_allowed))
                self.assertEqual(set(summary['status_rates']),
                                 {'no_signal', 'unknown', 'failed', 'unprocessed', 'ok'})
        serialized = json.dumps(data, allow_nan=False)
        for sentinel in ('PRIVATE_', '12:00:00', '0.987'):
            self.assertNotIn(sentinel, serialized)
            self.assertNotIn(sentinel, html)
        self.assertEqual(data['deduplication']['raw_records'], 1)

    def test_empty_input_renders_without_invented_rates(self):
        from ephemeral_feedback import build
        data = build([], {})
        self.assertEqual(data['weeks'], [])
        self.assertEqual(data['total_messages'], 0)
        self.assertIsNone(data['totals']['corrections']['signal_total'])
        self.assertIsNone(data['totals']['corrections']['status_rates']['ok'])
        self.assertIn('Histórico ou decisões insuficientes',
                      dashboard.render(data, date(2026, 8, 3)))

    def test_conservative_renderer_trends_blocked_by_partial_sources_or_missing_dates(self):
        from ephemeral_feedback import build
        from datetime import timedelta
        inputs, satisfaction = [], []
        for index in range(8):
            stamp = (date(2026, 6, 1) + timedelta(weeks=index)).isoformat() + 'T12:00:00Z'
            inputs.append(item(str(index), stamp))
            satisfaction.append(row(str(index), 'insatisfacao' if index < 4 else 'neutro'))
        data = build(inputs, {'satisfaction': satisfaction})
        cutoff = date(2026, 7, 27)
        self.assertTrue(dashboard.compare(data, cutoff)['available'])
        self.assertIn('redução recente', dashboard.render(data, cutoff))
        data['observed_history'] = {'source_status': 'partial'}
        self.assertEqual(dashboard.compare(data, cutoff), {'available': False})
        self.assertNotIn('redução recente', dashboard.render(data, cutoff))
        data.pop('observed_history')
        data['missing_timestamps']['messages'] = 1
        self.assertEqual(dashboard.compare(data, cutoff), {'available': False})
        data = build(inputs, {'satisfaction': satisfaction[:-1]})
        self.assertEqual(dashboard.compare(data, cutoff), {'available': False})

    def test_invalid_and_malformed_timestamps_stay_separate_with_empty_calendar_buckets(self):
        from ephemeral_feedback import build
        items = [item('a'), item('b', '2026-07-20T12:00:00Z')]
        for index, stamp in enumerate((None, 'invalid', True, float('nan'), float('inf'), [])):
            items.extend([item(f'{index}-{copy}', stamp, text='PRIVATE_SAME_TEXT')
                          for copy in range(2)])
        for index, refs in enumerate((None, [], [None], ['bad'], {})):
            candidate = item('malformed-' + str(index))
            candidate['provenance'] = refs
            items.append(candidate)
        data = build(items, {})
        self.assertEqual([w['messages'] for w in data['weeks']], [1, 0, 1])
        self.assertEqual([w['week'] for w in data['weeks']],
                         ['2026-07-06', '2026-07-13', '2026-07-20'])
        self.assertEqual(data['missing_timestamps']['messages'], 17)
        self.assertEqual(data['dated_messages'], 2)
        self.assertEqual(data['total_messages'], 19)
        self.assertIsNone(data['weeks'][1]['satisfaction']['signal_rate'])
        self.assertIsNone(data['weeks'][1]['satisfaction']['counts']['satisfacao'])
        self.assertFalse(dashboard.compare(data, date(2026, 8, 3))['available'])
        self.assertIn('PARCIAL', dashboard.render(data, date(2026, 8, 3)))

    def test_conflicting_copy_labels_abstain_but_repeated_id_conflicts_fail(self):
        from ephemeral_feedback import build
        items = [item('a', text='PRIVATE_FULL_TEXT'), item('b', text='PRIVATE_FULL_TEXT')]
        data = build(items, {'satisfaction': [row('a'), row('b', 'insatisfacao')],
                             'corrections': [row('a', 'correcao'), row('a', 'ambos'),
                                             row('b', 'correcao')]})
        s = data['totals']['satisfaction']
        self.assertEqual((s['ok'], s['unknown'], s['counts']['satisfacao']), (1, 1, 0))
        self.assertEqual(data['totals']['corrections']['failed'], 1)
        self.assertEqual(data['deduplication']['duplicate_label_disagreements'],
                         {'satisfaction': 1, 'corrections': 0})
        reverse = {name: list(reversed(rows)) for name, rows in {
            'satisfaction': [row('a'), row('b', 'insatisfacao')],
            'corrections': [row('a', 'correcao'), row('a', 'ambos'), row('b', 'correcao')]}.items()}
        self.assertEqual(build(list(reversed(items)), reverse), data)

    def test_duplicate_failure_dominates_missing_copy_and_never_becomes_success(self):
        from ephemeral_feedback import build
        items = [item('a', text='PRIVATE_FULL_TEXT'), item('b', text='PRIVATE_FULL_TEXT')]
        data = build(items, {'satisfaction': [row('a', status='error')],
                             'corrections': [row('a', 'correcao')]})
        self.assertEqual(data['total_messages'], 1)
        self.assertEqual(data['totals']['satisfaction']['failed'], 1)
        self.assertEqual(data['totals']['satisfaction']['unprocessed'], 0)
        self.assertIsNone(data['totals']['satisfaction']['counts']['satisfacao'])
        self.assertEqual(data['totals']['corrections']['unprocessed'], 1)
        self.assertEqual(data['deduplication']['duplicate_copies_removed'], 1)
        self.assertIn('PARCIAL', dashboard.render(data, date(2026, 8, 3)))

    def test_build_renders_real_schema_and_preserves_status_denominators(self):
        from ephemeral_feedback import build
        items = [item(str(i)) for i in range(5)]
        labels = {'satisfaction': [row('0'), row('1', 'neutro'),
                                   row('2', 'indeterminado'), row('3', status='error')],
                  'corrections': [row('0', 'ambos')]}
        data = build(items, labels)
        summary = data['weeks'][0]['satisfaction']
        self.assertEqual(summary['denominator'], 5)
        self.assertEqual(summary['rates']['satisfacao'], 1 / 5)
        self.assertEqual((summary['ok'], summary['unknown'], summary['failed'],
                          summary['unprocessed']), (3, 1, 1, 1))
        self.assertEqual(data['weeks'][0]['corrections']['signal_total'], 1)
        self.assertIn('PARCIAL', dashboard.render(data, date(2026, 8, 3)))


if __name__ == '__main__':
    unittest.main()
