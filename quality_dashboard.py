"""Apresentação executiva pura e offline do contrato agregado de qualidade.

Não serializa eventos-fonte, identificadores ou relatórios técnicos. Os números
vêm do construtor da narrativa; somente a geometria dos gráficos é escalada aqui.
"""
from html import escape
import math
import textwrap


_STYLE = '''
:root { color-scheme: light; --ink: #172f39; --muted: #4c6068;
  --line: #d5e0df; --green: #1f624d; --amber: #805300; }
* { box-sizing: border-box; }
body { margin: 0; background: #eef3f2; color: var(--ink);
  font: 16px/1.65 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width: 1240px; margin: auto; padding: 52px 32px; }
header { padding: 32px; background: #153d38; color: #fff; border-radius: 20px; }
.eyebrow { font-size: .75rem; font-weight: 700; letter-spacing: .13em; }
h1 { font-size: clamp(2rem, 4vw, 3.3rem); line-height: 1.15; margin: 18px 0; }
h2 { font-size: 1.4rem; line-height: 1.35; margin: 0 0 18px; }
h3 { font-size: 1.1rem; line-height: 1.4; margin: 0 0 10px; }
p { margin: 8px 0; }
header p { color: #e2efeb; }
.status { border-left: 3px solid #f3cf80; margin-top: 26px; padding-left: 18px; }
.status h2 { color: #fff; margin-bottom: 6px; }
section { margin-top: 36px; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }
.kpi, .insight, .chart, .segment { background: #fff; border: 1px solid var(--line);
  border-radius: 14px; padding: 24px; min-width: 0; }
.kpi { border-top: 4px solid #697a7e; }
.kpi.positive { border-top-color: var(--green); }
.kpi.warning { border-top-color: var(--amber); }
.kpi h2 { font-size: 1rem; color: var(--muted); }
.metric { font-size: clamp(1.7rem, 3vw, 2.5rem); font-weight: 750; line-height: 1.2; }
.metric.qualitative { font-size: 1.65rem; line-height: 1.3; overflow-wrap: normal; }
.base { font-weight: 650; }
.kpi p:not(.metric):not(.base), .unit { font-size: .9rem; color: var(--muted); }
.insights { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }
.action { margin-top: 20px; background: #f0f5f3; padding: 14px; border-radius: 8px; }
.chart, .segment { margin-top: 18px; }
.chart-scroll, .table-scroll { overflow-x: auto; max-width: 100%; }
.chart-scroll:focus, summary:focus { outline: 3px solid var(--amber); outline-offset: 4px; }
svg { display: block; width: 100%; min-width: 1000px; height: auto; }
svg text { font-family: system-ui, sans-serif; font-size: 16px; fill: #172f39; }
summary { cursor: pointer; color: var(--green); font-weight: 650; padding: 12px 0; }
details { border-top: 1px solid var(--line); margin-top: 12px; }
table { width: 100%; border-collapse: collapse; text-align: left; font-size: .92rem; }
caption { text-align: left; font-weight: 700; padding: 12px 0; }
th, td { border-bottom: 1px solid var(--line); padding: 12px; vertical-align: top;
  overflow-wrap: anywhere; min-width: 110px; }
th { background: #f0f5f3; }
li { padding-bottom: 8px; }
.empty { color: var(--muted); padding: 22px; border: 1px dashed #6c7d81; border-radius: 8px; }
footer { margin-top: 36px; border-top: 1px solid var(--line); padding-top: 20px;
  color: var(--muted); font-size: .85rem; }
h1, h2, h3, p, li { overflow-wrap: anywhere; }
@media (max-width: 640px) {
  main { padding: 20px 14px; } header { padding: 24px 20px; border-radius: 14px; }
  .kpis, .insights { grid-template-columns: 1fr; }
  .kpi, .insight, .chart, .segment { padding: 20px; }
}
@media print {
  @page { size: landscape; margin: 12mm; }
  body { background: #fff; font-size: 10pt; }
  main { max-width: none; padding: 0; }
  header { background: #fff; color: #172f39; border: 1px solid #697a7e; padding: 20px; }
  header p, .status h2 { color: #172f39; }
  section { margin-top: 20px; }
  .kpis { grid-template-columns: repeat(3, 1fr); }
  .insights { grid-template-columns: 1fr 1fr; }
  .kpi, .insight, tr { break-inside: avoid; }
  .chart-scroll, .table-scroll { overflow: visible; }
  svg { min-width: 0; width: 100%; }
  details > :not(summary) { display: block !important; }
  summary { display: none; }
  th, td { min-width: 0; padding: 6px; }
  h2, h3 { break-after: avoid; }
}
'''



def _chart(chart, index):
    title = _text(chart.get('title'))
    description = _text(chart.get('description'))
    rows = chart.get('rows', [])
    table_rows = ''.join(
        '<tr>' + ''.join(f'<td>{_text(v)}</td>' for v in (
            r.get('label'), r.get('display'),
            r.get('denominator') if r.get('denominator') is not None else 'Sem base',
            r.get('note'))) + '</tr>' for r in rows
    )
    table = ('<details><summary>Ver dados em tabela</summary><div class="table-scroll">'
             f'<table><caption>{title}</caption><thead><tr><th scope="col">Categoria</th>'
             '<th scope="col">Valor</th><th scope="col">Base</th><th scope="col">Observação</th>'
             f'</tr></thead><tbody>{table_rows}</tbody></table></div></details>')
    if not rows:
        visual = f'<p class="empty">{_text(chart.get("empty_reason") or "Sem dados disponíveis.")}</p>'
    else:
        def measurable(value):
            return isinstance(value, (int, float)) and math.isfinite(value)

        maximum = max((max(0, r['value']) for r in rows if measurable(r.get('value'))), default=0)
        y = 20
        shapes = []
        for row in rows:
            label = str(row.get('label', ''))
            lines = textwrap.wrap(label, width=42) or ['']
            row_height = max(78, len(lines) * 21 + 32)
            # Preserve the complete label in an accessible title, wrap visible text.
            wrapped = ''.join(f'<tspan x="16" dy="{0 if n == 0 else 21}">{_text(line)}</tspan>'
                              for n, line in enumerate(lines))
            shapes.append(f'<g><title>{_text(label)}</title><text x="16" y="{y + 22}">{wrapped}</text>')
            value = row.get('value')
            if measurable(value):
                width = max(0, value) / maximum * 370 if maximum else 0
                shapes.append(f'<rect x="400" y="{y + 5}" width="{width:.3f}" height="24" rx="5" fill="#24735d"/>')
                display = row.get('display')
            else:
                display = 'Sem dado · ' + str(row.get('display', 'Não mensurável'))
            shapes.append(f'<text x="790" y="{y + 23}">{_text(display)}</text></g>')
            y += row_height
        visual = (f'<div class="chart-scroll" tabindex="0" role="region" aria-label="Gráfico: {title}">'
                  f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
                  f'aria-labelledby="chart-title-{index} chart-desc-{index}" viewBox="0 0 1120 {y}">'
                  f'<title id="chart-title-{index}">{title}</title>'
                  f'<desc id="chart-desc-{index}">{description} Unidade: {_text(chart.get("unit"))}. '
                  'Barras horizontais; valores ausentes são indicados como sem dado.</desc>'
                  + ''.join(shapes) + '</svg></div>')
    return (f'<article class="chart"><h3>{title}</h3><p>{description}</p>'
            f'<p class="unit">Unidade: {_text(chart.get("unit"))}</p>{visual}{table}</article>')


def _text(value):
    return escape(str(value) if value is not None else '', quote=True)


def _tone(value):
    return {'positive': 'positive', 'warning': 'warning'}.get(value, 'neutral')


def _segments(segments):
    tables = []
    for segment in segments:
        dimension = _text(segment.get('dimension'))
        rows = ''.join(
            '<tr>' + ''.join(f'<td>{_text(row.get(field))}</td>' for field in (
                'label', 'tasks', 'first_display', 'correction_display', 'unknown_display')) + '</tr>'
            for row in segment.get('rows', [])
        )
        tables.append(
            f'<article class="segment"><h3>{dimension}</h3><div class="table-scroll">'
            f'<table><caption>Recorte por {dimension}</caption><thead><tr>'
            '<th scope="col">Grupo</th><th scope="col">Grupos</th>'
            '<th scope="col">Primeira tentativa</th><th scope="col">Correções</th>'
            f'<th scope="col">Desconhecido</th></tr></thead><tbody>{rows}</tbody></table></div></article>'
        )
    return ''.join(tables)


def render(story) -> str:
    """Retorna HTML PT-BR determinístico e autocontido, sem alterar a narrativa."""
    scope = story.get('scope', {})
    status = story.get('status', {})
    cards = ''.join(
        f'<article class="kpi {_tone(k.get("tone"))}">'
        f'<h2>{_text(k.get("title"))}</h2><p class="metric{" qualitative" if k.get("display") == "Não mensurável" else ""}">{_text(k.get("display"))}</p>'
        f'<p class="base">{_text(k.get("base"))}</p><p>{_text(k.get("note"))}</p></article>'
        for k in story.get('kpis', [])
    )
    insights = ''.join(
        f'<article class="insight {_tone(i.get("tone"))}"><h3>{_text(i.get("title"))}</h3>'
        f'<p>{_text(i.get("body"))}</p><p class="action"><strong>Ação recomendada</strong><br>'
        f'{_text(i.get("action"))}</p></article>' for i in story.get('insights', [])
    )
    notes = ''.join(f'<li>{_text(n)}</li>' for n in story.get('quality_notes', []))
    methods = ''.join(f'<li>{_text(n)}</li>' for n in story.get('methodology', []))
    title = _text(story.get('title', 'Qualidade das entregas'))
    return f'''<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'none'; connect-src 'none'; style-src 'unsafe-inline'; img-src 'none'; font-src 'none'; base-uri 'none'; form-action 'none'">
<title>{title}</title><style>{_STYLE}</style></head><body><main>
<header><p class="eyebrow">QUALIDADE DAS ENTREGAS · VISÃO EXECUTIVA</p><h1>{title}</h1>
<p>{_text(scope.get('period_label'))} · {_text(scope.get('tasks'))} grupos analisados · {_text(scope.get('events'))} eventos</p>
<div class="status"><h2>{_text(status.get('title'))}</h2><p>{_text(status.get('message'))}</p></div></header>
<section class="kpis" aria-label="Indicadores principais">{cards}</section>
<section><h2>O que podemos afirmar</h2><div class="insights">{insights}</div></section>
<section><h2>Evidências em números</h2>{''.join(_chart(c, n) for n, c in enumerate(story.get('charts', [])))}</section>
<section><h2>O que ainda não podemos afirmar</h2><ul>{notes}</ul></section>
<section><h2>Metodologia</h2><ul>{methods}</ul></section>
<section><h2>Segmentos</h2>{_segments(story.get('segments', []))}</section>
<footer>Leitura descritiva · Versão da narrativa {_text(story.get('narrative_version'))}</footer>
</main></body></html>'''
