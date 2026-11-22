"""Synthetic-only behavioral tests for the public HTML renderer."""
import copy
from html.parser import HTMLParser
import re
import unittest
import xml.etree.ElementTree as ET

from quality_dashboard import render


def story():
    return {
        'title': 'Qualidade das entregas', 'narrative_version': '1',
        'scope': {'tasks': 4, 'events': 12, 'period_label': 'Período sintético'},
        'status': {'code': 'partial', 'title': 'Leitura parcial', 'message': 'Cobertura limitada.'},
        'kpis': [{'key': 'first', 'title': 'Entrega na primeira tentativa', 'display': '100%',
                  'base': '1 / 1', 'note': 'Base observada, não garantia futura.', 'tone': 'positive'},
                 {'key': 'speed', 'title': 'Velocidade', 'display': 'Não mensurável',
                  'base': 'Sem duração válida', 'note': 'Não estimar.', 'tone': 'neutral'}],
        'insights': [{'key': 'delivery', 'title': 'Entrega observada', 'body': 'Uma entrega confirmada.',
                      'action': 'Se a lacuna persistir, revisar a coleta.', 'tone': 'warning'}],
        'charts': [], 'segments': [],
        'methodology': ['A base considera somente tarefas observadas.'],
        'quality_notes': ['Não é possível atribuir causalidade.'],
    }


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.text = []
        self.in_style = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))
        if tag == 'style':
            self.in_style = True

    def handle_endtag(self, tag):
        if tag == 'style':
            self.in_style = False

    def handle_data(self, data):
        if not self.in_style:
            self.text.append(data)


class DashboardTests(unittest.TestCase):
    def test_executive_reading_order_and_supplied_numbers(self):
        html = render(story())
        doc = Document(html)
        text = ' '.join(doc.text)
        expected = ['Qualidade das entregas', 'Leitura parcial', 'Entrega na primeira tentativa',
                    'O que podemos afirmar', 'Entrega observada', 'Ação recomendada',
                    'O que ainda não podemos afirmar', 'Metodologia']
        positions = [text.index(item) for item in expected]
        self.assertEqual(positions, sorted(positions))
        for value in ['100%', '1 / 1', 'Não mensurável', 'Período sintético',
                      '4 grupos analisados', '12 eventos', 'Se a lacuna persistir, revisar a coleta.']:
            self.assertIn(value, text)
        self.assertIn(('html', {'lang': 'pt-BR'}), doc.elements)

    def test_charts_preserve_null_zero_labels_and_equivalent_table(self):
        data = story()
        data['charts'] = [{
            'key': 'outcomes', 'title': 'Entregas por resultado',
            'description': 'Contagens observadas, sem estimativa.', 'unit': 'tarefas',
            'rows': [
                {'label': 'Confirmada ' * 30, 'value': 7, 'display': '7 tarefas', 'denominator': 9, 'note': 'Base restrita'},
                {'label': 'Sem correção', 'value': 0, 'display': '0 tarefas', 'denominator': 9, 'note': ''},
                {'label': 'Duração', 'value': None, 'display': 'Não mensurável', 'denominator': None, 'note': 'Sem relógio'},
            ], 'empty_reason': None,
        }]
        html = render(data)
        svgs = re.findall(r'<svg\b.*?</svg>', html, re.S)
        self.assertEqual(len(svgs), 1)
        root = ET.fromstring(svgs[0])
        ns = {'s': 'http://www.w3.org/2000/svg'}
        self.assertEqual(root.attrib['role'], 'img')
        self.assertIn('viewBox', root.attrib)
        svg_title = root.find('s:title', ns)
        svg_desc = root.find('s:desc', ns)
        assert svg_title is not None
        assert svg_desc is not None
        self.assertTrue(svg_title.text)
        self.assertTrue(svg_desc.text)
        rects = root.findall('.//s:rect', ns)
        self.assertEqual(len(rects), 2)
        self.assertEqual(float(rects[1].attrib['width']), 0)
        self.assertGreater(float(rects[0].attrib['width']), 0)
        self.assertIn('Sem dado', ''.join(root.itertext()))
        self.assertIn('Confirmada ' * 30, ''.join(root.itertext()))
        doc = Document(html)
        self.assertTrue(any(tag == 'table' for tag, _ in doc.elements))
        self.assertIn('<details>', html)
        self.assertIn('Base restrita', ' '.join(doc.text))
        self.assertIn('9', ' '.join(doc.text))
        data['charts'][0]['rows'] = []
        data['charts'][0]['empty_reason'] = 'Não há observações elegíveis.'
        empty = render(data)
        self.assertIn('Não há observações elegíveis.', empty)
        self.assertNotIn('<svg', empty)

    def test_document_is_offline_responsive_and_printable(self):
        html = render(story())
        doc = Document(html)
        metas = [attrs for tag, attrs in doc.elements if tag == 'meta']
        csp = next((m['content'] for m in metas if m.get('http-equiv') == 'Content-Security-Policy'), '')
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'none'", csp)
        self.assertIn("connect-src 'none'", csp)
        self.assertIn("style-src 'unsafe-inline'", csp)
        self.assertNotIn('@import', html)
        for tag, attrs in doc.elements:
            self.assertNotIn(tag, ['script', 'link', 'iframe', 'img', 'object', 'embed'])
            self.assertFalse(any(k.startswith('on') or k in ('src', 'href') for k in attrs))
        self.assertIn('@media print', html)
        self.assertIn('@media (max-width:', html)
        self.assertIn('overflow-x: auto', html)
        self.assertIn('system-ui', html)
        self.assertIn('details >', html)

    def test_segments_present_supplied_displays_without_analytics(self):
        data = story()
        data['segments'] = [{'dimension': 'Tipo de trabalho', 'rows': [{
            'label': 'Pesquisa sintética', 'tasks': 4, 'first_display': '1 / 2',
            'correction_display': '1 / 4', 'unknown_display': '2 / 4',
        }]}]
        text = ' '.join(Document(render(data)).text)
        for item in ['Segmentos', 'Tipo de trabalho', 'Pesquisa sintética', '1 / 2', '1 / 4', '2 / 4']:
            self.assertIn(item, text)
        self.assertLess(text.index('Metodologia'), text.index('Segmentos'))

    def test_escape_all_external_text_and_ignore_unlisted_private_fields(self):
        malicious = '\"><script>alert(1)</script><img src="https://invalid.example" onerror="x"> & <fim>'
        data = story()
        data['title'] = malicious
        data['scope']['period_label'] = malicious
        for field in ['title', 'message', 'code']:
            data['status'][field] = malicious
        for field in ['title', 'display', 'base', 'note', 'tone', 'key']:
            data['kpis'][0][field] = malicious
        for field in ['title', 'body', 'action', 'tone', 'key']:
            data['insights'][0][field] = malicious
        data['charts'] = [{'key': malicious, 'title': malicious, 'description': malicious,
                           'unit': malicious, 'empty_reason': malicious,
                           'rows': [{'label': malicious, 'value': None, 'display': malicious,
                                     'denominator': None, 'note': malicious}]}]
        data['segments'] = [{'dimension': malicious, 'rows': [{'label': malicious, 'tasks': 1,
                             'first_display': malicious, 'correction_display': malicious,
                             'unknown_display': malicious}]}]
        data['methodology'] = [malicious]
        data['quality_notes'] = [malicious]
        data['narrative_version'] = malicious
        data['raw_report'] = {'event_text': 'PRIVATE_SENTINEL', 'id': 'PRIVATE_SENTINEL'}
        for collection in ['kpis', 'insights', 'charts', 'segments']:
            data[collection][0]['event_text'] = 'PRIVATE_SENTINEL'
        before = copy.deepcopy(data)
        html = render(data)
        self.assertEqual(data, before)
        self.assertEqual(html, render(data))
        self.assertNotIn('PRIVATE_SENTINEL', html)
        self.assertNotIn(malicious, html)
        self.assertIn(malicious, ' '.join(Document(html).text))
        for tag, attrs in Document(html).elements:
            self.assertNotIn(tag, ['script', 'img'])
            self.assertFalse(any(k.startswith('on') for k in attrs))
        for svg in re.findall(r'<svg\b.*?</svg>', html, re.S):
            root = ET.fromstring(svg)
            self.assertIn(malicious, ''.join(root.itertext()))

    def test_empty_story_remains_an_honest_readable_document(self):
        data = story()
        for field in ['kpis', 'insights', 'charts', 'segments', 'methodology', 'quality_notes']:
            data[field] = []
        html = render(data)
        self.assertNotIn('<svg', html)
        self.assertNotIn('100%', ' '.join(Document(html).text))
        self.assertIn('O que ainda não podemos afirmar', html)
        self.assertEqual(html, render(copy.deepcopy(data)))


if __name__ == '__main__':
    unittest.main()
