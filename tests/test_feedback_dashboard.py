"""Synthetic public-contract tests; never read a consumer profile."""
import copy
from datetime import date, timedelta
from pathlib import Path
import re
from typing import Any
import unittest
from xml.etree import ElementTree

import analysis
import feedback_dashboard as dashboard

CUTOFF = date(2032, 3, 6)
MONDAY = CUTOFF - timedelta(days=CUTOFF.weekday())


def fixture() -> dict[str, Any]:
    weeks = []
    for i, (n, k) in enumerate([(100, 20)] * 4 + [(10, 5), (90, 9), (100, 10), (200, 20), (10, 10)]):
        weeks.append({'week': str(MONDAY + timedelta(weeks=i-8)), 'messages': n,
                      'satisfaction': {'counts': {'insatisfacao': k, 'satisfacao': 0, 'mista': 0,
                                                  'neutro': n-k, 'indeterminado': 0}, 'unknown': 0},
                      'corrections': {'counts': {'correcao': 0, 'redirecionamento': 0, 'ambos': 0,
                                                 'sem_intervencao': n, 'indeterminado': 0}, 'unknown': 0}})
    return {'weeks': weeks}


class DashboardTest(unittest.TestCase):
    def test_long_history_axis_is_readable_and_weekly_table_has_headers(self):
        data=fixture();template=copy.deepcopy(data['weeks'][0]);data['weeks']=[]
        for i in range(20):
            row=copy.deepcopy(template);row['week']=str(MONDAY-timedelta(weeks=19-i));data['weeks'].append(row)
        page=dashboard.render(data,CUTOFF)
        svg=ElementTree.fromstring(re.findall(r'<svg\b.*?</svg>',page,re.S)[0])
        ticks=svg.findall('.//{http://www.w3.org/2000/svg}text[@font-size="11"]')
        self.assertLessEqual(len(ticks),10)
        self.assertEqual(ticks[-1].text,str(MONDAY))
        positions=[float(t.attrib['x']) for t in ticks]
        self.assertTrue(all(b-a>=85 for a,b in zip(positions,positions[1:])))
        table=page.split('<h2>Contagens e taxas semanais</h2>',1)[1].split('</table>',1)[0]
        self.assertIn('<thead>',table)
        self.assertIn('Insatisfação</th>',table)
        self.assertIn('Só correção</th>',table)

    def test_calendar_weighting_and_median_exclude_open_week(self):
        result = dashboard.compare(fixture(), CUTOFF)
        self.assertTrue(result['available'])
        self.assertEqual(result['previous']['messages'], 400)
        self.assertEqual(result['recent']['messages'], 400)
        self.assertEqual(result['recent']['negative'], 44)
        self.assertEqual(result['recent']['rate'], 11)
        self.assertEqual(result['recent']['median_weekly_rate'], 10)
        self.assertEqual(result['delta_pp'], -9)
        self.assertEqual(result['relative_change'], -45)
        self.assertEqual(result['recent']['end'], str(MONDAY-timedelta(days=1)))

    def test_offline_five_charts_and_no_consumer_qualification(self):
        data = fixture()
        data['private_text'] = 'SYNTHETIC_NOT_FOR_EXPORT'
        page = dashboard.render(data, CUTOFF)
        charts = re.findall(r'<svg\b.*?</svg>', page, re.S)
        self.assertEqual(len(charts), 5)
        for chart in charts:
            ElementTree.fromstring(chart)
        for text in ('Média móvel ponderada', 'Mediana móvel', 'por 100 mensagens',
                     'não homologada', 'America/Sao_Paulo', 'semana em aberto', '11,0%'):
            self.assertIn(text, page)
        self.assertNotIn('SYNTHETIC_NOT_FOR_EXPORT', page)
        self.assertNotRegex(page, r'<script|(?:src|href)=[\"\x27]https?://|8/10|7/10')
        self.assertIn('Mediana móvel · 4 semanas: 10,0%', page)

    def test_partial_processing_blocks_comparison_and_is_visible(self):
        data = fixture()
        group = data['weeks'][4]['satisfaction']
        group.update({'ok': 8, 'failed': 1, 'unprocessed': 1})
        self.assertFalse(dashboard.compare(data, CUTOFF)['available'])
        page = dashboard.render(data, CUTOFF)
        self.assertIn('PARCIAL', page)
        self.assertIn('80,0%', page)
        self.assertIn('Falhas', page)
        self.assertIn('Não processadas', page)

    def test_public_independent_rubrics_load_in_analysis(self):
        root = Path(__file__).resolve().parents[1]
        expected = {
            'satisfaction': {'satisfacao', 'insatisfacao', 'mista', 'neutro', 'indeterminado'},
            'corrections': {'correcao', 'redirecionamento', 'ambos', 'sem_intervencao', 'indeterminado'},
        }
        for name, labels in expected.items():
            rubric = analysis.load_rubric(root / 'rubrics' / (name+'.json'))
            self.assertEqual(rubric['id'], name)
            self.assertEqual(set(rubric['criteria']), labels)
            self.assertEqual(rubric['kinds'], ['feedback'])
            self.assertEqual(rubric['unknown'], 'indeterminado')
            self.assertEqual(rubric['aggregation'], 'unanimous')
            self.assertIn('não confiáveis', rubric['instructions'])
            self.assertIn('independente', rubric['instructions'])

    def test_missing_timestamps_are_partial_not_success(self):
        data = fixture()
        data['missing_timestamps'] = {'messages': 3, 'private_text': 'DO_NOT_EXPORT'}
        page = dashboard.render(data, CUTOFF)
        self.assertIn('PARCIAL', page)
        self.assertIn('Sem timestamp: 3', page)
        self.assertNotIn('DO_NOT_EXPORT', page)
        self.assertFalse(dashboard.compare(data,CUTOFF)['available'])
        self.assertNotIn('Os sinais sugerem redução recente',page)

    def test_incomplete_source_blocks_trend_claims(self):
        data=fixture();data['observed_history']={'source_status':'partial'}
        self.assertFalse(dashboard.compare(data,CUTOFF)['available'])
        self.assertIn('PARCIAL',dashboard.render(data,CUTOFF))

    def test_empty_weeks_not_zero_in_median(self):
        data = fixture()
        row = data['weeks'][4]
        row['messages'] = 0
        for name in ('satisfaction', 'corrections'):
            row[name]['counts'] = dict.fromkeys(row[name]['counts'])
        result = dashboard.compare(data, CUTOFF)
        self.assertTrue(result['available'])
        self.assertEqual(result['recent']['median_weekly_rate'], 10)
        self.assertEqual(result['recent']['valid_weeks'], 3)
        data['weeks'][5]['satisfaction']['counts']['insatisfacao'] = None
        self.assertFalse(dashboard.compare(data, CUTOFF)['available'])
        self.assertIn('PARCIAL', dashboard.render(data, CUTOFF))

    def test_calendar_gap_cannot_be_compressed_to_four_observed_rows(self):
        data = fixture()
        del data['weeks'][5]
        self.assertFalse(dashboard.compare(data, CUTOFF)['available'])
        self.assertNotIn('Mediana móvel · 4 semanas: 10,0%', dashboard.render(data, CUTOFF))

    def test_empty_data_has_no_fake_rates(self):
        data = {'weeks': []}
        self.assertFalse(dashboard.compare(data, CUTOFF)['available'])
        page = dashboard.render(data, CUTOFF)
        self.assertEqual(page.count('<svg '), 5)
        self.assertNotIn('redução recente', page)
        self.assertIn('não homologada', page)

    def test_comparison_and_hover_explain_denominators(self):
        page = dashboard.render(fixture(), CUTOFF)
        for expected in ('Mediana das taxas semanais', '44 / 400 mensagens',
                         'base da janela: 400 mensagens', '4 taxas semanais válidas',
                         'semana tem o mesmo peso'):
            self.assertTrue(expected in page, 'missing denominator explanation')

    def test_invalid_aggregates_fail_closed_without_echo(self):
        mutations = [
            lambda data: data['weeks'].append(copy.deepcopy(data['weeks'][0])),
            lambda data: data['weeks'][0].update(messages=-1),
            lambda data: data['weeks'][0].update(messages=True),
            lambda data: data['weeks'][0]['satisfaction']['counts'].update(insatisfacao='<svg onload=attack()>'),
        ]
        for mutate in mutations:
            data = fixture()
            mutate(data)
            for action in (dashboard.render, dashboard.compare):
                with self.assertRaisesRegex(ValueError, '^invalid_aggregate$'):
                    action(data, CUTOFF)

    def test_extra_fields_do_not_affect_metrics_or_leak(self):
        data = fixture()
        for row in data['weeks']:
            row['satisfaction']['counts']['private_text'] = 'PRIVATE_SYNTHETIC'
        data['semantic_qualification'] = 'approved'
        page = dashboard.render(data, CUTOFF)
        self.assertNotIn('PRIVATE_SYNTHETIC', page)
        self.assertIn('não homologada', page)
        self.assertTrue(dashboard.compare(data, CUTOFF)['available'])
        self.assertEqual(dashboard.compare(data, CUTOFF)['recent']['rate'], 11)

    def test_rates_for_coverage_and_missing_interventions_remain_observable(self):
        data = fixture()
        row = data['weeks'][-1]
        row['corrections'].update(ok=0, failed=4, unprocessed=6, partial=True)
        row['corrections']['counts'] = dict.fromkeys(row['corrections']['counts'])
        page = dashboard.render(data, CUTOFF)
        self.assertTrue('4 / 40,0%' in page, 'failed rate missing')
        self.assertTrue('6 / 60,0%' in page, 'unprocessed rate missing')
        charts = {ElementTree.fromstring(svg).attrib['id']: ElementTree.fromstring(svg)
                  for svg in re.findall(r'<svg\b.*?</svg>', page, re.S)}
        tips = [el.text or '' for el in charts['intervencoes-taxa'].iter()
                if el.tag.endswith('title')]
        self.assertFalse(any(str(MONDAY) in tip and '0,0%' in tip for tip in tips))

    def test_table_escapes_display_metadata(self):
        data = fixture()
        # Optional metadata is escaped even when a caller violates its numeric
        # convention; no active HTML may be introduced into the document.
        data['missing_timestamps'] = {'messages': '<img src=x onerror=attack()>'}
        page = dashboard.render(data, CUTOFF)
        self.assertFalse('<img' in page)
        self.assertTrue('&lt;img src=x onerror=attack()&gt;' in page)

    def test_order_is_not_significant_and_input_not_mutated(self):
        data = fixture()
        original = copy.deepcopy(data)
        data['weeks'].reverse()
        self.assertEqual(dashboard.compare(data, CUTOFF), dashboard.compare(original, CUTOFF))
        self.assertEqual(dashboard.render(data, CUTOFF), dashboard.render(original, CUTOFF))
        self.assertEqual(data['weeks'][0], original['weeks'][-1])

    def test_configured_report_calendar_is_not_mislabeled(self):
        data = fixture()
        data['timezone'] = 'UTC'
        page = dashboard.render(data, CUTOFF)
        self.assertTrue('calendário UTC' in page, 'configured calendar mislabeled')
        self.assertNotIn('calendário America/Sao_Paulo', page)


if __name__ == '__main__':
    unittest.main()
