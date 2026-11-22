"""Contrato público de métricas; dados sintéticos, sem rede ou perfis reais."""
import unittest

from quality_metrics import aggregate


def task(**fields):
    result = dict(outcome='unknown', first_attempt_resolved=None,
                  correction_count=0, extra_attempts=None, source_complete=True,
                  association_uncertain=False, resolution_seconds=None,
                  cost=None, currency=None, tokens=None, interventions={},
                  abandonment='unknown', action_failure_count=0)
    result.update(fields)
    return result


class AggregateTests(unittest.TestCase):
    def test_first_attempt_rate_has_known_denominator_and_wilson(self):
        metrics = aggregate([task(first_attempt_resolved=True),
                             task(first_attempt_resolved=False), task()])
        self.assertIn('first_attempt_resolution', metrics)
        rate = metrics['first_attempt_resolution']
        self.assertEqual((rate['numerator'], rate['denominator'], rate['value']), (1, 2, .5))
        self.assertAlmostEqual(rate['wilson95']['lower'], .09453120573423074)
        self.assertAlmostEqual(rate['wilson95']['upper'], .9054687942657693)
        self.assertEqual(rate['coverage']['unknown'], 1)
        self.assertEqual(rate['coverage']['total'], 3)
        self.assertAlmostEqual(rate['coverage']['value'], 2 / 3)

    def test_correction_requires_complete_certain_sources_not_satisfaction(self):
        metrics = aggregate([task(correction_count=2), task(),
                             task(source_complete=False, correction_count=1),
                             task(association_uncertain=True, correction_count=1)])
        self.assertIn('tasks_with_correction', metrics)
        rate = metrics['tasks_with_correction']
        self.assertEqual((rate['numerator'], rate['denominator']), (1, 2))
        self.assertEqual(rate['coverage']['unknown'], 2)
        self.assertEqual(metrics['no_observed_correction']['numerator'], 1)
        self.assertNotIn('satisfaction', metrics)
        self.assertEqual(metrics['unknown_resolution']['numerator'], 4)
        self.assertEqual(metrics['resolved_with_evidence']['numerator'], 0)

    def test_quantiles_are_nearest_rank_not_interpolated(self):
        rows = [task(outcome='resolved_with_evidence', resolution_seconds=n,
                     extra_attempts=n) for n in range(1, 5)]
        rows += [task(), task(outcome='unresolved', resolution_seconds=999)]
        metrics = aggregate(iter(rows))
        self.assertIn('resolution_seconds', metrics)
        duration = metrics['resolution_seconds']
        self.assertEqual((duration['median'], duration['p90'], duration['p95']), (2, 4, 4))
        self.assertEqual(duration['coverage']['unknown'], 2)
        self.assertEqual(metrics['extra_attempts']['median'], 2)
        self.assertEqual(metrics['extra_attempts']['sum'], 10)
        self.assertEqual(metrics['extra_attempts']['coverage']['known'], 4)

    def test_cost_per_resolved_includes_cost_of_unresolved_tasks(self):
        metrics = aggregate([task(outcome='resolved_with_evidence', cost=2, currency='BRL'),
                             task(outcome='unresolved', cost=3, currency='BRL')])
        self.assertIn('cost_per_resolved_task', metrics)
        cost = metrics['cost_per_resolved_task']
        self.assertEqual((cost['numerator'], cost['denominator'], cost['value']), (5, 1, 5))
        self.assertEqual(cost['currency'], 'BRL')
        self.assertEqual(cost['coverage']['known'], 2)
        self.assertEqual(metrics['cost_total']['value'], 5)
        self.assertIsNone(cost.get('wilson95'))  # razão monetária, não taxa binomial

    def test_cost_is_null_unless_every_attributable_task_has_complete_same_currency_cost(self):
        base = task(outcome='resolved_with_evidence', cost=2, currency='BRL')
        for fields, reason in [({'cost': None, 'tokens': 100}, 'missing_cost'),
                               ({'cost': 3, 'currency': 'USD'}, 'mixed_currency'),
                               ({'cost': 3, 'currency': None}, 'missing_currency'),
                               ({'cost': 3, 'source_complete': False}, 'incomplete_source')]:
            with self.subTest(reason=reason):
                cost = aggregate([base, task(currency='BRL', **fields) if 'currency' not in fields
                                  else task(**fields)])['cost_per_resolved_task']
                self.assertIsNone(cost['value'])
                self.assertIsNone(cost['numerator'])
                self.assertIn(reason, cost['unknown_reasons'])
        cost = aggregate([base, task(cost=None)])['cost_per_resolved_task']
        self.assertEqual(cost['coverage']['known'], 1)
        self.assertEqual(cost['coverage']['unknown_ratio'], .5)
        self.assertEqual(cost['denominator'], 1)
        excluded = aggregate([base, task(association_uncertain=True)])['cost_per_resolved_task']
        self.assertEqual(excluded['value'], 2)
        self.assertEqual(excluded['attributable_tasks'], 1)
        self.assertEqual(excluded['excluded_uncertain_tasks'], 1)

    def test_interventions_failures_abandonment_and_tokens_stay_separate(self):
        metrics = aggregate([task(interventions={'approval': 2, 'clarification': 1},
                                  action_failure_count=3, tokens=0, abandonment='explicit'),
                             task(interventions={'approval': 1}, tokens=100,
                                  abandonment='possible'),
                             task(abandonment='right_censored'),
                             task(abandonment='natural_session_end'), task()])
        self.assertIn('interventions', metrics)
        self.assertEqual(metrics['interventions']['approval']['count'], 3)
        self.assertEqual(metrics['interventions']['approval']['tasks']['numerator'], 2)
        self.assertEqual(metrics['action_failures']['count'], 3)
        self.assertEqual(metrics['action_failures']['tasks']['numerator'], 1)
        self.assertEqual(metrics['tasks_with_correction']['numerator'], 0)
        self.assertEqual(metrics['abandonment']['explicit']['numerator'], 1)
        self.assertEqual(metrics['abandonment']['possible']['numerator'], 1)
        self.assertEqual(metrics['abandonment']['right_censored']['numerator'], 1)
        self.assertEqual(metrics['abandonment']['natural_session_end']['numerator'], 1)
        self.assertEqual(metrics['abandonment']['unknown']['numerator'], 1)
        self.assertEqual(metrics['tokens']['sum'], 100)
        self.assertEqual(metrics['tokens']['coverage']['known'], 2)
        self.assertIsNone(metrics['cost_total']['value'])

    def test_incomplete_or_uncertain_tasks_cannot_prove_first_attempt(self):
        rate = aggregate([task(first_attempt_resolved=True, source_complete=False),
                          task(first_attempt_resolved=False, association_uncertain=True),
                          task(first_attempt_resolved=True)])['first_attempt_resolution']
        self.assertEqual((rate['numerator'], rate['denominator']), (1, 1))
        self.assertEqual(rate['coverage']['unknown'], 2)

    def test_empty_zero_and_invalid_numbers_remain_json_safe(self):
        import copy
        import json
        empty = aggregate([])
        self.assertIsNone(empty['first_attempt_resolution']['value'])
        self.assertIsNone(empty['first_attempt_resolution']['wilson95'])
        self.assertIsNone(empty['resolution_seconds']['median'])
        self.assertIsNone(empty['cost_total']['value'])
        rows = [task(outcome='resolved_with_evidence', resolution_seconds=x,
                     cost=x, currency='BRL', tokens=x)
                for x in (None, -1, float('inf'), float('nan'), True, 0)]
        before = copy.deepcopy(rows[-1])
        metrics = aggregate(rows)
        self.assertEqual(rows[-1], before)
        self.assertEqual(metrics['resolution_seconds']['count'], 1)
        self.assertEqual(metrics['resolution_seconds']['median'], 0)
        self.assertEqual(metrics['tokens']['coverage']['known'], 1)
        self.assertIsNone(metrics['cost_total']['value'])
        json.dumps(metrics, allow_nan=False)
        zero = aggregate([task(cost=0, currency='BRL')])
        self.assertEqual(zero['cost_total']['value'], 0)
        self.assertIsNone(zero['cost_per_resolved_task']['value'])

    def test_cost_unknown_reason_distinguishes_no_resolved_denominator(self):
        metrics = aggregate([task(outcome='unresolved', cost=0, currency='BRL')])
        self.assertEqual(metrics['cost_total']['value'], 0)
        cost = metrics['cost_per_resolved_task']
        self.assertIsNone(cost['value'])
        self.assertIn('no_resolved_tasks', cost['unknown_reasons'])
        self.assertEqual(metrics['cost_total']['unknown_reasons'], [])


if __name__ == '__main__':
    unittest.main()
