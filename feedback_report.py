"""Relatório privado offline (stdlib).

API: build(root) -> dict; lê corpus.json e <rubrica>/analysis/results.jsonl.
Só status exatamente 'ok' com rótulo válido é decisão. Ausência não é unknown.
Taxas são frações de TODAS as mensagens feedback datadas da semana.
Contagens de rótulos são observadas, não estimadas; null indica nenhuma decisão.
CLI: python3 -B feedback_report.py ROOT [--timezone UTC]. Sem rede/inferência.
O padrão preserva America/Sao_Paulo; UTC não exige tzdata do sistema.
"""
import argparse
import csv
import io
import os
import stat
import tempfile
from html import escape
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LABELS = {
    'satisfaction': ('satisfacao', 'insatisfacao', 'mista', 'neutro', 'indeterminado'),
    'corrections': ('correcao', 'redirecionamento', 'ambos', 'sem_intervencao', 'indeterminado'),
}
DEFAULT_TIMEZONE = 'America/Sao_Paulo'


def _timezone(name):
    # No timezone database access at import time. UTC is stdlib-only even on
    # Windows installations without an IANA database; never silently shift dates.
    return timezone.utc if name == 'UTC' else ZoneInfo(name)


def _summary(items, rows, name):
    counts = dict.fromkeys(LABELS[name], 0)
    failed = unprocessed = ok = 0
    for item in items:
        row = rows.get(item['id'])
        if row is None:
            unprocessed += 1
        elif (row.get('status') != 'ok' or not isinstance(row.get('label'), str)
              or row.get('label') not in counts):
            failed += 1
        else:
            counts[row['label']] += 1
            ok += 1
    unknown = counts['indeterminado']
    n = len(items)
    if not ok:
        counts = dict.fromkeys(counts)
    signal_labels = LABELS[name][:3]
    signal_total = sum(counts[k] for k in signal_labels) if ok else None
    no_signal = counts['neutro' if name == 'satisfaction' else 'sem_intervencao']
    status_counts = {'no_signal': no_signal, 'unknown': unknown, 'failed': failed,
                     'unprocessed': unprocessed, 'ok': ok}
    return {'counts': counts,
            'status_rates': {k: v / n if v is not None and n else None
                             for k, v in status_counts.items()},
            'signal_total': signal_total,
            'signal_rate': signal_total / n if signal_total is not None and n else None,
            'no_signal': no_signal,
            'rates': {k: v / n if v is not None and n else None for k, v in counts.items()},
            'ok': ok, 'unknown': unknown, 'failed': failed, 'unprocessed': unprocessed,
            'partial': bool(failed or unprocessed), 'denominator': n}


def _read_rows(path):
    """Read one rubric, rejecting malformed input and abstaining on conflicts.

    Identical repeated labels are harmless; conflicting status/label rows become
    a failed decision, independent of order. Error details never reach exports.
    """
    rows = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            previous = rows.get(row['id'])
            if previous is not None and (
                    previous.get('status'), previous.get('label')) != (
                    row.get('status'), row.get('label')):
                row = {'id': row['id'], 'status': 'error'}
            rows[row['id']] = row
    return rows


def _check_tree(root):
    """Reject prepared links/special files before reading or writing a campaign."""
    root = Path(root)
    for path in (root, *root.rglob('*')):
        info = path.lstat()
        if (stat.S_ISLNK(info.st_mode) or
                (not stat.S_ISDIR(info.st_mode) and
                 (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1))):
            raise ValueError('invalid_snapshot')


def _write_text(path, content):
    """Private atomic replacement; never truncate an existing linked inode."""
    path = Path(path)
    if path.parent.is_symlink():
        raise ValueError('invalid_snapshot')
    try:
        info = path.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
        raise ValueError('invalid_snapshot')
    fd, temporary = tempfile.mkstemp(prefix='.feedback-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build(root, *, timezone_name=DEFAULT_TIMEZONE):
    """Write aggregate JSON/CSV/HTML and return the historical report schema.

    timezone_name optionally selects a calendar, without changing input files.
    Missing IANA data raises rather than silently using a different calendar.
    """
    _timezone(timezone_name)
    root = Path(root)
    _check_tree(root)
    items = [i for i in json.loads((root / 'corpus.json').read_text(encoding='utf-8'))['items']
             if i.get('kind') == 'feedback']
    rows = {name: _read_rows(root / name / 'analysis' / 'results.jsonl')
            for name in LABELS}
    buckets = {}
    missing = []
    for item in items:
        d = _date(item, timezone_name=timezone_name)
        if d is None:
            missing.append(item)
            continue
        monday = d - timedelta(days=d.weekday())
        buckets.setdefault(monday, []).append(item)
    weeks = []
    if buckets:
        monday = min(buckets)
        while monday <= max(buckets):
            group = buckets.get(monday, [])
            weeks.append({'week': monday.isoformat(), 'messages': len(group),
                          **{name: _summary(group, rows[name], name) for name in LABELS}})
            monday += timedelta(days=7)
    data = {'timezone': timezone_name, 'weeks': weeks,
            'dated_messages': len(items) - len(missing), 'total_messages': len(items),
            'totals': {name: _summary(items, rows[name], name) for name in LABELS},
            'missing_timestamps': {'messages': len(missing),
                **{name: _summary(missing, rows[name], name) for name in LABELS}}}
    _write(root, data)
    return data


def _date(item, *, timezone_name=DEFAULT_TIMEZONE):
    # Um item é uma mensagem: usar o primeiro timestamp válido, nunca duplicar
    # a mensagem por haver múltiplas proveniências. ISO sem offset é horário local.
    tz = _timezone(timezone_name)
    for provenance in item.get('provenance', []):
        t = provenance.get('timestamp')
        try:
            if isinstance(t, bool) or t is None:
                continue
            if isinstance(t, (int, float)):
                dt = datetime.fromtimestamp(t, tz)
            elif isinstance(t, str):
                dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
            else:
                continue
            return dt.astimezone(tz).date()
        except (ValueError, OverflowError, OSError):
            continue
    return None


TITLES = {'satisfaction': 'Satisfação e insatisfação',
          'corrections': 'Correções e redirecionamentos'}
DISPLAY = {'satisfacao': 'Satisfação', 'insatisfacao': 'Insatisfação', 'mista': 'Mista',
           'neutro': 'Sem sinal', 'indeterminado': 'Indeterminado',
           'correcao': 'Correção', 'redirecionamento': 'Redirecionamento',
           'ambos': 'Ambos', 'sem_intervencao': 'Sem intervenção'}


def _fmt(value, rate=False):
    if value is None:
        return '—'
    return f'{100 * value:.1f}%' if rate else str(value)


def _chart(weeks, name):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="360" '
             f'viewBox="0 0 1000 360" role="img" aria-label="{TITLES[name]} por semana">',
             f'<title>{TITLES[name]} — taxas semanais observadas</title>',
             '<rect width="1000" height="360" fill="white"/>']
    for pct in (0, 25, 50, 75, 100):
        y = 260 - pct * 2
        parts.append(f'<path d="M60 {y}H970" stroke="#ddd"/>'
                     f'<text x="8" y="{y + 5}" font-size="13">{pct}%</text>')
    colors = ('#087f5b', '#c92a2a', '#7950b2') if name == 'satisfaction' else ('#1864ab', '#d9480f', '#7950b2')
    for j, label in enumerate(LABELS[name][:3]):
        color = colors[j]
        parts.append(f'<text x="{60 + 300 * j}" y="25" fill="{color}" font-size="15">'
                     f'{DISPLAY[label]}</text>')
        previous = None
        for i, week in enumerate(weeks):
            value = week[name]['rates'][label]
            x = 70 + i * 890 / max(1, len(weeks) - 1)
            if value is None:
                previous = None
                continue
            y = 260 - value * 200
            if previous is not None:
                parts.append(f'<path d="M{previous[0]:.2f} {previous[1]:.2f}L{x:.2f} {y:.2f}" '
                             f'stroke="{color}" fill="none"/>')
            partial = ' PARCIAL' if week[name]['partial'] else ''
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}">'
                         f'<title>{week["week"]}: {DISPLAY[label]} '
                         f'{week[name]["counts"][label]}/{week["messages"]} '
                         f'({_fmt(value, True)}){partial}</title></circle>')
            previous = (x, y)
    stride = max(1, (len(weeks) + 9) // 10)
    for i, week in enumerate(weeks):
        if i % stride == 0 or i == len(weeks) - 1:
            x = 70 + i * 890 / max(1, len(weeks) - 1)
            parts.append(f'<text transform="translate({x:.2f},280) rotate(35)" '
                         f'font-size="12">{week["week"]}</text>')
    if not weeks:
        parts.append('<text x="200" y="150">Sem mensagens datadas</text>')
    parts.append('</svg>')
    return ''.join(parts)


def _table(groups, name):
    headers = ['Período', 'Mensagens'] + [DISPLAY[k] + ' n / taxa' for k in LABELS[name]]
    headers += ['Total com sinal n / taxa', 'Sem sinal n / taxa', 'Indeterminadas n / taxa',
                'Falhas n / taxa', 'Não processadas n / taxa', 'Cobertura', 'Estado']
    parts = ['<table><thead><tr>' + ''.join(f'<th>{h}</th>' for h in headers) + '</tr></thead><tbody>']
    for period, group in groups:
        s = group[name]
        cells = [period, group['messages']]
        cells += [f'{_fmt(s["counts"][k])} / {_fmt(s["rates"][k], True)}' for k in LABELS[name]]
        cells += [f'{_fmt(s["signal_total"])} / {_fmt(s["signal_rate"], True)}']
        cells += [f'{_fmt(s[k])} / {_fmt(s["status_rates"][k], True)}'
                  for k in ('no_signal', 'unknown', 'failed', 'unprocessed')]
        cells += [f'{s["ok"]}/{group["messages"]}',
                  'PARCIAL' if s['partial'] else ('Sem mensagens' if not group['messages'] else 'Completo')]
        parts.append('<tr>' + ''.join('<td>' + escape(str(c)) + '</td>' for c in cells) + '</tr>')
    return ''.join(parts) + '</tbody></table>'


def _write(root, data):
    _write_text(root / 'report.json', json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    fields = ['week', 'messages']
    for name in LABELS:
        for label in LABELS[name]:
            fields += [f'{name}_{label}_count', f'{name}_{label}_rate']
        fields += [f'{name}_{k}' for k in ('ok', 'no_signal', 'unknown', 'failed', 'unprocessed', 'partial', 'signal_total', 'signal_rate')]
        fields += [f'{name}_{k}_rate' for k in ('ok', 'no_signal', 'unknown', 'failed', 'unprocessed')]
    with io.StringIO(newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for week in data['weeks']:
            row = {'week': week['week'], 'messages': week['messages']}
            for name in LABELS:
                s = week[name]
                for label in LABELS[name]:
                    row[f'{name}_{label}_count'] = s['counts'][label]
                    row[f'{name}_{label}_rate'] = s['rates'][label]
                for k in ('ok', 'no_signal', 'unknown', 'failed', 'unprocessed', 'partial', 'signal_total', 'signal_rate'):
                    row[f'{name}_{k}'] = s[k]
                for k, value in s['status_rates'].items():
                    row[f'{name}_{k}_rate'] = value
            writer.writerow(row)
        _write_text(root / 'weekly.csv', stream.getvalue())
    parts = ['<!doctype html><html lang="pt-BR"><meta charset="utf-8">',
             '<title>Tendências semanais de feedback</title>',
             '<style>body{font:16px system-ui;margin:28px;color:#222}svg{width:1000px;min-width:1000px}'
             '.scroll{overflow-x:auto}table{border-collapse:collapse;font-size:13px;margin:20px 0}'
             'td,th{border:1px solid #ccc;padding:7px;text-align:right}h2{margin-top:35px}</style>',
             '<h1>Tendências semanais de feedback</h1>',
             f'<p>Fuso: {escape(data["timezone"])}. Semanas de segunda a domingo. '
             'Denominador de cada taxa semanal: todas as mensagens feedback datadas da semana, '
             'inclusive falhas e não processadas. Taxas observadas, não estimativas de satisfação global. '
             'Rubricas independentes; uma mensagem pode conter satisfação e correção.</p>',
             '<p>Sem sinal não é indeterminado. Falha não é decisão. Ausência de resultado é não processada. '
             '— e células CSV vazias significam ausência de decisões/taxa indefinida, nunca zero. '
             'Semanas vazias não têm taxa; linhas dos gráficos são interrompidas. '
             'PARCIAL indica falhas ou resultados ainda ausentes; zeros parciais são apenas observados.</p>',
             f'<p>Total: {data["total_messages"]} mensagens; datadas: {data["dated_messages"]}; '
             f'sem timestamp válido: {data["missing_timestamps"]["messages"]} (fora dos gráficos).</p>']
    groups = [(w['week'], w) for w in data['weeks']]
    for name in LABELS:
        parts += [f'<h2>{TITLES[name]}</h2>']
        total = data['totals'][name]
        state = 'PARCIAL' if total['partial'] else 'Completo'
        parts += [f'<p><strong>{state} — {total["ok"]}/{data["total_messages"]} '
                  'mensagens com resultado válido (incluindo indeterminadas).</strong></p>']
        if name == 'corrections':
            parts += ['<p>Correção, redirecionamento e ambos são séries exclusivas. '
                      'Total com sinal = correção + redirecionamento + ambos, cada mensagem uma única vez.</p>']
        else:
            parts += ['<p>Satisfação, insatisfação e mista são séries exclusivas; mista é mostrada separadamente.</p>']
        parts += ['<div class="scroll">' + _chart(data['weeks'], name) + '</div>',
                  '<div class="scroll">' + _table(groups, name) + '</div>',
                  '<h3>Resumo e mensagens sem data</h3>',
                  '<div class="scroll">' + _table([
                      ('Total (inclui sem data)', {'messages': data['total_messages'], **data['totals']}),
                      ('Sem timestamp válido', data['missing_timestamps'])], name) + '</div>']
    parts += ['<p>Taxas do resumo usam todas as mensagens do respectivo grupo. '
              'Timestamp: primeira proveniência válida; ISO sem offset é interpretado no fuso local. '
              'Classificações são dados de entrada; este relatório não executa modelos nem mede sua acurácia.</p></html>']
    _write_text(root / 'report.html', ''.join(parts))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gerar relatório privado de feedback (offline).')
    parser.add_argument('root', type=Path)
    parser.add_argument('--timezone', default=DEFAULT_TIMEZONE, dest='timezone_name',
                        help='Fuso IANA; UTC funciona sem banco tzdata instalado.')
    args = parser.parse_args()
    try:
        build(args.root, timezone_name=args.timezone_name)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, 'Erro: entrada inválida ou acesso aos arquivos indisponível.\n')
    print('Relatório gerado: report.json, weekly.csv e report.html.')
