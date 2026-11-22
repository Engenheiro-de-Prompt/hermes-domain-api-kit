"""Comportamentos executivos sobre projeções sintéticas; sem modelo/rede."""
import copy
import json
from pathlib import Path
import unittest
import quality

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    return json.loads((ROOT / 'examples/quality-events.synthetic.json').read_text())


class StoryTests(unittest.TestCase):
    def test_existing_renderer_explains_outcomes_visually_without_private_fields(self):
        data = fixture()
        tasks, report = quality.evaluate(data['events'], tenant_id='synthetic')
        before = copy.deepcopy(report)
        output = quality.render(report)
        self.assertIn('Desfechos observados', output)
        self.assertIn('<svg', output)
        self.assertIn('3 / 6', output)
        self.assertEqual(report, before)
        self.assertEqual(output, quality.render(report))
        self.assertNotIn('objective1', output)

    def test_editorial_bands_prioritize_missing_evidence_over_performance(self):
        from quality_story import build
        tasks, report = quality.evaluate(fixture()['events'], tenant_id='synthetic')
        story = build(report, tasks)
        self.assertEqual(story.get('bands', {}).get('first'), 'below_half')
        self.assertEqual(story.get('bands', {}).get('correction'), 'at_least_30_percent')
        self.assertEqual(story['status']['code'], 'evidence_gap')
        self.assertIn('exploratória', ' '.join(story['quality_notes']))
        cards = {c['key']: c for c in story['kpis']}
        self.assertEqual(cards['correction']['display'], '33,3%')
        self.assertEqual(cards['duration']['display'], '3 min')
        self.assertEqual(cards['cost']['display'], 'Não mensurável')
        self.assertIn('5 / 6', cards['cost']['base'])
        self.assertEqual(cards['extra']['display'], '2')
        self.assertIn('30%', ' '.join(story['methodology']))

    def test_chart_bases_close_and_operational_buckets_are_explicit(self):
        from quality_story import build
        tasks, report = quality.evaluate(fixture()['events'], tenant_id='synthetic')
        before = copy.deepcopy(tasks)
        story = build(report, iter(tasks))
        charts = {c['key']: c for c in story['charts']}
        self.assertIn('first_attempt', charts)
        self.assertEqual([r['value'] for r in charts['first_attempt']['rows']], [1, 3, 2])
        self.assertEqual([r['value'] for r in charts['corrections']['rows']], [2, 4, 0])
        self.assertEqual([r['value'] for r in charts['attempts']['rows']], [4, 2, 0, 0])
        self.assertEqual(sum(r['value'] for r in charts['duration']['rows']), 3)
        self.assertIn('300', charts['duration']['description'])
        for group in story['segments']:
            self.assertEqual(sum(r['tasks'] for r in group['rows']), 6)
        self.assertTrue(story['segments'])
        self.assertEqual(tasks, before)

    def test_model_abstention_failure_pending_are_not_observed_task_outcomes(self):
        from quality_story import build
        tasks, report = quality.evaluate(fixture()['events'], tenant_id='synthetic')
        report['classifier'] = dict(labels=7, indeterminate=3, failed=1,
            eligible_event_labels=8, estimated_full_campaign_calls=8, models=['synthetic-model'],
            distribution={'outcome:resolvida_com_evidencia': 1})
        story = build(report, tasks)
        charts = {c['key']: c for c in story['charts']}
        self.assertIn('classifier_processing', charts)
        self.assertEqual([r['value'] for r in charts['classifier_processing']['rows']], [4, 2, 1, 1])
        self.assertEqual(charts['outcomes']['rows'][0]['value'], 3)
        self.assertIn('não é acurácia', ' '.join(story['quality_notes']))
        self.assertTrue(any(i['key'] == 'classifier' for i in story['insights']))

    def test_cli_writes_auditable_narrative_with_full_bucket_projection(self):
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as temporary:
            td = str(Path(temporary).resolve())
            args = [sys.executable, '-B', 'cli.py', 'quality-report', '--input',
                    str(ROOT / 'examples/quality-events.synthetic.json'), '--tenant', 'synthetic', '--work', td]
            result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            base = Path(td) / 'quality'
            self.assertTrue((base / 'narrative.json').exists())
            story = json.loads((base / 'narrative.json').read_text())
            self.assertIn('duration', [c['key'] for c in story['charts']])
            self.assertIn('UTC', story['scope']['period_label'])
            self.assertEqual(story['bands']['first'], 'below_half')
            self.assertEqual(json.loads(result.stdout)['classifier']['eligible_event_labels'], 5)
            first_html = (base / 'dashboard.html').read_bytes()
            html = first_html.decode('utf-8')
            self.assertIn('Modelo: processamento', html)
            self.assertIn('DADOS SINTÉTICOS', html)
            self.assertIn('Classificação de texto não executada', html)
            again = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(first_html, (base / 'dashboard.html').read_bytes())
            self.assertNotIn('objective1', (base / 'narrative.json').read_text())

    def test_operational_signals_preserve_separate_bases_and_unknown(self):
        from quality_story import build
        tasks, report = quality.evaluate(fixture()['events'], tenant_id='synthetic')
        charts = {c['key']: c for c in build(report, tasks)['charts']}
        self.assertIn('abandonment', charts)
        self.assertEqual(sum(r['value'] for r in charts['abandonment']['rows']), 6)
        self.assertEqual(charts['abandonment']['rows'][0]['value'], 1)
        self.assertEqual(charts['failures']['rows'][0]['value'], 0)
        self.assertEqual(sum(r['value'] for r in charts['interventions']['rows']),
                         sum(v['count'] for v in report['metrics']['interventions'].values()))
        _, partial = quality.evaluate([dict(fixture()['events'][0], source_complete=False)], tenant_id='synthetic')
        partial_charts = {c['key']: c for c in build(partial)['charts']}
        self.assertIsNone(partial_charts['failures']['rows'][0]['value'])

    def test_empty_and_unrepresentable_period_never_become_good_performance(self):
        from quality_story import build
        tasks, report = quality.evaluate([], tenant_id='synthetic')
        story = build(report, tasks)
        self.assertEqual(story['status']['code'], 'empty')
        self.assertEqual(story['bands']['first'], 'unknown')
        self.assertEqual(story['bands']['correction'], 'unknown')
        self.assertEqual(story['kpis'][0]['display'], 'Não mensurável')
        self.assertEqual(story['segments'], [])
        report['observation'] = {'first_event_timestamp': 1e300, 'last_event_timestamp': 1e300}
        self.assertTrue(build(report)['scope']['period_label'].startswith('Período não mensurável'))

    def test_editorial_band_boundaries_use_exact_observed_fractions(self):
        from quality_metrics import aggregate
        from quality_story import build
        for successes, corrections, first_band, correction_band in (
                (0, 0, 'below_half', 'none_observed'), (9, 5, 'below_half', 'some_observed'),
                (10, 6, 'at_least_half', 'at_least_30_percent'), (20, 0, 'all_eligible', 'none_observed')):
            projections = [dict(outcome='resolved_with_evidence' if i < successes else 'unresolved',
                first_attempt_resolved=i < successes, source_complete=True, association_uncertain=False,
                correction_count=int(i >= 20 - corrections), correction_types={}, correction_severities={})
                for i in range(20)]
            report = dict(metrics=aggregate(projections), total_tasks=20, coverage={'unique_events': 20})
            story = build(report)
            self.assertEqual(story['bands']['first'], first_band)
            self.assertEqual(story['bands']['correction'], correction_band)
            self.assertEqual(story['bands']['eligibility'], 'complete')
            self.assertFalse(any('Amostra exploratória' in note for note in story['quality_notes']))
            self.assertTrue(any('não metas, SLAs' in text for text in story['methodology']))

    def test_aggregate_story_never_exports_raw_text_identifiers_or_unrecognized_fields(self):
        from quality_story import build
        events = fixture()['events']
        sentinel = 'PRIVATE_RAW_SENTINEL'
        for event in events:
            event['text'] = sentinel
        tasks, report = quality.evaluate(events, tenant_id='synthetic')
        for task in tasks:
            task['task_id'] = sentinel
            task['source_event_ids'] = [sentinel]
            task['classifications'] = [{'raw': sentinel}]
        report['limitations'] = [sentinel]
        report['unrecognized'] = sentinel
        before = copy.deepcopy((report, tasks))
        story = build(report, tasks)
        self.assertNotIn(sentinel, json.dumps(story))
        self.assertEqual((report, tasks), before)
        self.assertEqual(story, build(report, reversed(tasks)))


if __name__ == '__main__':

    unittest.main()
