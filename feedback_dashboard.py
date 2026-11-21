"""Offline presentation of aggregate weekly feedback; no I/O or inference."""


from datetime import date, timedelta
from statistics import median
from typing import Any


LABELS = {
    'satisfaction': ('insatisfacao', 'satisfacao', 'mista', 'neutro', 'indeterminado'),
    'corrections': ('correcao', 'redirecionamento', 'ambos', 'sem_intervencao', 'indeterminado'),
}


def _weeks(data, cutoff):
    """Validate and project an allowlist without reflecting malformed values."""
    try:
        if type(cutoff) is not date or not isinstance(data['weeks'], list):
            raise ValueError()
        rows, seen = [], set()
        for original in data['weeks']:
            day = date.fromisoformat(original['week'])
            if day.weekday() or day in seen:
                raise ValueError()
            seen.add(day)
            n = original['messages']
            if type(n) is not int or not 0 <= n <= 10**15:
                raise ValueError()
            row = {'week': day.isoformat(), 'messages': n}
            for name, labels in LABELS.items():
                source = original.get(name, {})
                counts = {k: source.get('counts', {}).get(k) for k in labels}
                if any(v is not None and (type(v) is not int or not 0 <= v <= n) for v in counts.values()):
                    raise ValueError()
                group: dict[str, Any] = {'counts': counts}
                for key in ('ok', 'unknown', 'failed', 'unprocessed'):
                    if key in source:
                        value = source[key]
                        if value is not None and (type(value) is not int or not 0 <= value <= n):
                            raise ValueError()
                        group[key] = value
                if 'partial' in source:
                    if type(source['partial']) is not bool:
                        raise ValueError()
                    group['partial'] = source['partial']
                row[name] = group
            rows.append(row)
        return sorted(rows, key=lambda row: row['week'])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        raise ValueError('invalid_aggregate') from None


def _processed(group):
    # The legacy weeks schema has no status metadata. Its observed counts
    # provide a conservative coverage estimate; null is never a zero decision.
    return group.get('ok', sum(v for v in group['counts'].values() if type(v) is int))


def _complete(row, name='satisfaction'):
    group = row[name]
    return (not group.get('partial', False) and not group.get('failed', 0)
            and not group.get('unprocessed', 0) and _processed(group) == row['messages']
            and (not row['messages'] or all(v is not None for v in group['counts'].values())))


def _window(indexed, start):
    days = [start + timedelta(weeks=i) for i in range(4)]
    if any(day not in indexed for day in days):
        return None
    rows = [indexed[day] for day in days]
    if any(row['messages'] and (row['satisfaction']['counts'].get('insatisfacao') is None or not _complete(row)) for row in rows):
        return None
    n = sum(row['messages'] for row in rows)
    k = sum(row['satisfaction']['counts']['insatisfacao'] or 0 for row in rows)
    rates = [100 * row['satisfaction']['counts']['insatisfacao'] / row['messages']
             for row in rows if row['messages']]
    return {'start': str(start), 'end': str(start + timedelta(days=27)),
            'messages': n, 'negative': k, 'rate': 100*k/n if n else None,
            'median_weekly_rate': median(rates) if rates else None,
            'valid_weeks': len(rates)}


def _source_complete(data):
    return (not data.get('missing_timestamps', {}).get('messages', 0)
            and data.get('observed_history', {}).get('source_status', 'ok') == 'ok')


def compare(data, cutoff: date) -> dict[str, Any]:
    """Compare four closed Monday weeks against the four preceding weeks.

    Rates use every dated message as denominator. Empty weeks remain in the
    calendar but have no rate and are excluded from the median.
    """
    if not _source_complete(data):
        return {'available': False}
    monday = cutoff - timedelta(days=cutoff.weekday())
    indexed = {date.fromisoformat(row['week']): row for row in _weeks(data, cutoff)}
    previous = _window(indexed, monday - timedelta(weeks=8))
    recent = _window(indexed, monday - timedelta(weeks=4))
    if not previous or not recent or previous['rate'] is None or recent['rate'] is None:
        return {'available': False}
    delta = recent['rate'] - previous['rate']
    return {'available': True, 'previous': previous, 'recent': recent,
            'delta_pp': delta, 'relative_change': 100*delta/previous['rate'] if previous['rate'] else None}


def render(data, cutoff: date):
    """Return offline HTML; only aggregate fields are consumed, never raw text.

    ``week`` is a local Monday ISO date (America/Sao_Paulo by default).
    The caller aggregates timestamps in that calendar before calling render.
    Missing decisions stay missing; output is descriptive, not certification.
    """
    from html import escape
    import math

    esc = lambda value: escape(str(value), quote=True)
    num = lambda value: '—' if value is None else f'{value:.1f}'.replace('.', ',')
    weeks = _weeks(data, cutoff)
    indexed = {date.fromisoformat(row['week']): row for row in weeks}
    monday = cutoff - timedelta(days=cutoff.weekday())

    def values(group, label, rate=False):
        result = []
        for row in weeks:
            value = row[group]['counts'].get(label)
            result.append((100*value/row['messages'] if rate else value)
                          if row['messages'] and value is not None else None)
        return result

    def chart(key, title, series, percent=False):
        top = max(5, math.ceil(max([v for _, _, vals in series for v in vals if v is not None] + [1])/5)*5)
        x = lambda i: 65 + i*1020/max(1, len(weeks)-1)
        y = lambda v: 275 - 210*v/top
        svg = [f'<svg id="{key}" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1170 350" role="img" aria-label="{esc(title)}"><title>{esc(title)}</title>']
        for tick in range(6):
            value = top*tick/5
            svg.append(f'<line x1="65" x2="1085" y1="{y(value)}" y2="{y(value)}" stroke="#ddd"/><text x="5" y="{y(value)}">{value:g}{"%" if percent else ""}</text>')
        step = max(1, math.ceil(len(weeks)/10))
        for i, row in enumerate(weeks):
            if date.fromisoformat(row['week']) >= monday:
                svg.append(f'<rect x="{x(i)-15}" y="50" width="30" height="225" fill="#fef3c7"/><text x="{x(i)-20}" y="35">parcial</text>')
            if i == len(weeks)-1 or (i % step == 0 and len(weeks)-1-i >= step):
                svg.append(f'<text x="{x(i)}" y="310" text-anchor="middle" font-size="11">{esc(row["week"])}</text>')
        for name, color, vals in series:
            segments = [[]]
            for i, value in enumerate(vals):
                if value is None:
                    segments.append([])
                else:
                    segments[-1].append(f'{x(i):.2f},{y(value):.2f}')
            for segment in segments:
                if segment:
                    svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{" ".join(segment)}"/>')
            for i, value in enumerate(vals):
                if value is not None:
                    tip = f'{weeks[i]["week"]} • {name}: {num(value)}' + ('%' if percent else '')
                    if name.startswith(('Média móvel', 'Mediana móvel')):
                        end = date.fromisoformat(weeks[i]['week'])
                        window = _window(indexed, end-timedelta(weeks=3))
                        assert window is not None
                        tip += f' • base da janela: {window["messages"]} mensagens'
                        if name.startswith('Mediana móvel'):
                            tip += f' • {window["valid_weeks"]} taxas semanais válidas'
                    else:
                        tip += f' • base: {weeks[i]["messages"]} mensagens'
                        if any(not _complete(weeks[i], g) for g in LABELS):
                            tip += ' • PARCIAL'
                    svg.append(f'<circle cx="{x(i)}" cy="{y(value)}" r="4" fill="{color}"><title>{esc(tip)}</title></circle>')
        svg.append('</svg>')
        legend = ' · '.join(esc(name) for name, _, _ in series)
        return f'<section><h2>{esc(title)}</h2><p>{legend}</p><div class="scroll">{"".join(svg)}</div></section>'

    rolling, medians = [], []
    for row in weeks:
        end = date.fromisoformat(row['week'])
        window = _window(indexed, end-timedelta(weeks=3)) if end < monday and _source_complete(data) else None
        rolling.append(window['rate'] if window else None)
        medians.append(window['median_weekly_rate'] if window else None)
    intervention = []
    for row in weeks:
        counts = [row['corrections']['counts'].get(k) for k in ('correcao', 'redirecionamento', 'ambos')]
        intervention.append(100*sum(counts)/row['messages'] if row['messages'] and all(v is not None for v in counts) else None)
    graphs = [
        chart('insatisfacao-taxa', '1. Insatisfação por 100 mensagens', [
            ('Insatisfação semanal', '#dc2626', values('satisfaction', 'insatisfacao', True)),
            ('Média móvel ponderada · 4 semanas', '#7c3aed', rolling),
            ('Mediana móvel · 4 semanas', '#0891b2', medians)], True),
        chart('satisfacao-quantidade', '2. Quantidade de satisfação e insatisfação', [
            ('Insatisfação', '#dc2626', values('satisfaction', 'insatisfacao')),
            ('Satisfação', '#059669', values('satisfaction', 'satisfacao')),
            ('Mista', '#ca8a04', values('satisfaction', 'mista'))]),
        chart('intervencoes-quantidade', '3. Correções e redirecionamentos', [
            ('Só correção', '#2563eb', values('corrections', 'correcao')),
            ('Só redirecionamento', '#ea580c', values('corrections', 'redirecionamento')),
            ('Ambos (uma vez)', '#7c3aed', values('corrections', 'ambos'))]),
        chart('intervencoes-taxa', '4. Intervenções por 100 mensagens', [
            ('Correção e/ou redirecionamento', '#2563eb', intervention)], True),
        chart('cobertura', '5. Volume e incerteza', [
            ('Mensagens na base', '#475569', [row['messages'] for row in weeks]),
            ('Indeterminadas · satisfação', '#ca8a04', [row['satisfaction'].get('unknown') for row in weeks]),
            ('Indeterminadas · intervenções', '#ea580c', [row['corrections'].get('unknown') for row in weeks])])]
    comparison = compare(data, cutoff)
    comparison_html = ''
    conclusion = 'Histórico ou decisões insuficientes para comparar dois blocos completos.'
    if comparison['available']:
        direction = 'redução recente' if comparison['delta_pp'] < 0 else ('aumento recente' if comparison['delta_pp'] > 0 else 'estabilidade recente')
        conclusion = f'Os sinais sugerem {direction}: {num(comparison["previous"]["rate"])}% → {num(comparison["recent"]["rate"])}%. Não comprova melhora sustentada.'
        blocks = []
        for name, title in (('previous', 'Quatro semanas anteriores'), ('recent', 'Últimas quatro semanas fechadas')):
            block = comparison[name]
            blocks.append(f'<article><h3>{title}</h3><p>{esc(block["start"])} — {esc(block["end"])}</p>'
                          f'<p>{block["negative"]} / {block["messages"]} mensagens · {num(block["rate"])}%</p>'
                          f'<p>Mediana das taxas semanais: {num(block["median_weekly_rate"])}% '
                          f'({block["valid_weeks"]} semanas com mensagens)</p></article>')
        relative = num(comparison['relative_change'])+'%' if comparison['relative_change'] is not None else 'indisponível: taxa anterior zero'
        comparison_html = ('<section><h2>Comparação de períodos fechados</h2>'+''.join(blocks)
                           +f'<p>Variação: {num(comparison["delta_pp"])} p.p. · relativa: {relative}</p></section>')
    rows = []
    def count_rate(value, n):
        if value is None:
            return '—'
        return str(value)+' / '+(num(100*value/n)+'%' if n else '—')

    for row in weeks:
        partial = ' · parcial / semana em aberto' if date.fromisoformat(row['week']) >= monday else ''
        cells = [row['week']+partial, row['messages']]
        for group in ('satisfaction', 'corrections'):
            cells.extend(count_rate(row[group]['counts'].get(k), row['messages']) for k in LABELS[group])
        rows.append('<tr>'+''.join('<td>'+esc('—' if v is None else v)+'</td>' for v in cells)+'</tr>')
    coverage = []
    for row in weeks:
        for name in LABELS:
            group = row[name]
            ok = _processed(group)
            rate = 100*ok/row['messages'] if row['messages'] and ok is not None else None
            cells = [row['week'], name, row['messages'], ok, num(rate)+'%' if rate is not None else '—',
                     count_rate(group.get('unknown'), row['messages']),
                     count_rate(group.get('failed'), row['messages']),
                     count_rate(group.get('unprocessed'), row['messages']),
                     'PARCIAL' if not _complete(row, name) else ('Completo' if row['messages'] else 'Sem mensagens')]
            coverage.append('<tr>'+''.join('<td>'+esc('—' if v is None else v)+'</td>' for v in cells)+'</tr>')
    coverage_html = ('<section><h2>Cobertura de processamento</h2><div class="scroll"><table><thead><tr>'
                     '<th>Semana</th><th>Dimensão</th><th>Base</th><th>Processadas</th><th>Cobertura</th>'
                     '<th>Indeterminadas n / taxa</th><th>Falhas n / taxa</th><th>Não processadas n / taxa</th><th>Estado</th>'
                     '</tr></thead><tbody>'+''.join(coverage)+'</tbody></table></div></section>')
    weekly_headings = ['Semana', 'Mensagens', 'Insatisfação', 'Satisfação', 'Mista', 'Neutro',
                       'Indeterminadas (satisfação)', 'Só correção', 'Só redirecionamento',
                       'Ambos', 'Sem intervenção', 'Indeterminadas (intervenções)']
    weekly_header = '<thead><tr>'+''.join('<th scope="col">'+esc(h)+'</th>' for h in weekly_headings)+'</tr></thead>'
    missing_timestamps = data.get('missing_timestamps', {}).get('messages', 0)
    partial = not _source_complete(data) or any(not _complete(row, name) for row in weeks for name in LABELS)
    status = 'PARCIAL — cobertura incompleta; sinais observados não representam todas as decisões.' if partial else 'Cobertura observada na tabela; não garante todo o histórico.'
    css = 'body{font:16px/1.6 system-ui;background:#f1f5f9;color:#172033;margin:0}main{max-width:1200px;margin:auto;padding:24px}section,header{background:white;border:1px solid #ddd;border-radius:12px;padding:22px;margin:18px 0}.scroll{overflow:auto}svg{width:100%;min-width:800px}td,th{padding:8px;border-bottom:1px solid #ddd}table{border-collapse:collapse}.warning{background:#fffbeb}'
    return ('<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Tendências de feedback</title><style>'+css+'</style></head><body><main>'
            f'<header><h1>Tendências de feedback</h1><p>Corte {esc(cutoff.isoformat())} · calendário {esc(data.get("timezone", "America/Sao_Paulo"))}</p><h2>{esc(conclusion)}</h2></header>'
            + f'<section class="warning"><h2>{esc(status)}</h2><p>Sem timestamp: {esc(missing_timestamps)}. Fora das séries semanais.</p></section>' + coverage_html
            + comparison_html + ''.join(graphs) + '<section class="warning"><h2>Precisão semântica não homologada</h2>'
            '<p>Estatísticas descritivas, não prova causal, acurácia do modelo ou taxa objetiva de erros. '
            'Neutras não significam satisfação. Indeterminadas e falhas permanecem no denominador; ausência de decisão não é sucesso.</p></section>'
            '<section><h2>Como foi calculado</h2><p>Taxa = sinal ÷ todas as mensagens datadas × 100. '
            'Média móvel ponderada por mensagens e mediana das taxas semanais usam quatro semanas de calendário fechadas. '
            'Na média, mais mensagens dão mais peso; na mediana, cada semana tem o mesmo peso. '
            'A semana em aberto fica excluída. Semanas vazias não viram 0% na mediana. Lacunas indicam dados ausentes ou sem mensagens. '
            'Corrigir e expressar satisfação são dimensões independentes; ambos é contado uma vez.</p></section>'
            '<section><h2>Contagens e taxas semanais</h2><p>Células: contagem / taxa por todas as mensagens. Ordem: semana, mensagens, satisfação (insatisfação, satisfação, mista, neutro, indeterminado), '
            'intervenções (correção, redirecionamento, ambos, sem intervenção, indeterminado).</p><div class="scroll"><table>'
            + weekly_header + '<tbody>' + ''.join(rows) + '</tbody></table></div></section></main></body></html>')
