"""Métricas puras por tarefa, offline e somente com biblioteca padrão.

``aggregate(tasks)`` retorna diretamente o dicionário ``metrics`` do relatório.
Taxas têm numerator/denominator/value e wilson95 (lower/upper); denominador
zero produz value e intervalo nulos. A cobertura distingue conhecido de unknown.
Não há inferência de satisfação nem leitura de eventos, arquivos ou rede.

Contrato de saída:
* first_attempt_resolution: somente booleanos de fonte completa e associação certa;
* tasks_with_correction / no_observed_correction: mesmo universo completo/certo;
* unknown_resolution / resolved_with_evidence / unresolved: todas as tarefas;
* resolution_seconds: somente resolvidas com duração finita não negativa;
* extra_attempts / tokens: valores conhecidos no universo completo/certo;
* distribuições: count, sum (null sem observação), median, p90, p95, coverage;
* interventions: enum -> {count, tasks: taxa}; action_failures: mesmo formato;
* abandonment: cada estado separado, sem promover possível/censurado a abandono;
* cost_total / cost_per_resolved_task: custos de TODAS as tarefas atribuíveis,
  inclusive não resolvidas; custo nulo se qualquer fonte atribuível for incompleta,
  faltar custo/moeda, ou houver moedas distintas. O denominador monetário conta
  somente resolvidas nesse MESMO universo atribuível, nunca só as tarefas pagas.
  Tarefas com associação incerta são excluídas e contadas explicitamente.

coverage contém known/total/unknown/value/unknown_ratio. Em taxas de categorias
(outcome e abandonment), known significa que o estado, inclusive unknown, foi
contabilizado; a quantidade indeterminada é a própria categoria unknown.
Custos incluem unknown_reasons e cobertura individual de custos completos:
moedas distintas podem ter cobertura 100% mas soma nula, sem conversão implícita.
Tokens não se convertem em moeda. Zero explícito é válido; ausência nunca é zero.
O chamador valida a projeção, filtra o tenant e deduplica tarefas antes da chamada.
"""
import math


def _coverage(known, total):
    return {'known': known, 'total': total, 'unknown': total - known,
            'value': known / total if total else None,
            'unknown_ratio': (total - known) / total if total else None}


def _rate(numerator, denominator, total=None):
    value = numerator / denominator if denominator else None
    interval = None
    if denominator:
        value = numerator / denominator
        z = 1.959963984540054
        scale = 1 + z * z / denominator
        center = (value + z * z / (2 * denominator)) / scale
        radius = z * math.sqrt(value * (1 - value) / denominator
                               + z * z / (4 * denominator * denominator)) / scale
        interval = {'lower': max(0.0, center - radius),
                    'upper': min(1.0, center + radius)}
    result = {'numerator': numerator, 'denominator': denominator,
              'value': value, 'wilson95': interval}
    if total is not None:
        result['coverage'] = _coverage(denominator, total)
    return result


def aggregate(tasks):
    """Agrega projeções por tarefa sem alterar as entradas; aceita iteráveis."""
    tasks = list(tasks)
    total = len(tasks)
    certain = [t for t in tasks if t.get('source_complete') is True
               and t.get('association_uncertain') is False]
    eligible = [t for t in certain if type(t.get('first_attempt_resolved')) is bool]
    corrected = sum(t.get('correction_count', 0) > 0 for t in certain)
    metrics = {'first_attempt_resolution': _rate(
        sum(t['first_attempt_resolved'] for t in eligible), len(eligible), total),
        'tasks_with_correction': _rate(corrected, len(certain), total),
        'no_observed_correction': _rate(len(certain) - corrected, len(certain), total)}
    for key, outcome in [('unknown_resolution', 'unknown'),
                         ('resolved_with_evidence', 'resolved_with_evidence'),
                         ('unresolved', 'unresolved')]:
        metrics[key] = _rate(sum(t.get('outcome', 'unknown') == outcome for t in tasks), total, total)
    metrics['resolution_seconds'] = _distribution(
        [t.get('resolution_seconds') for t in tasks
         if t.get('outcome') == 'resolved_with_evidence'], total)
    metrics['extra_attempts'] = _distribution([t.get('extra_attempts') for t in certain], total)
    attributable = [t for t in tasks if t.get('association_uncertain') is False]
    priced = [t for t in attributable if _number(t.get('cost'))
              and isinstance(t.get('currency'), str) and t['currency'].strip()
              and t.get('source_complete') is True]
    currencies = {t['currency'] for t in priced}
    reasons = []
    if any(not _number(t.get('cost')) for t in attributable):
        reasons.append('missing_cost')
    if any(not isinstance(t.get('currency'), str) or not t['currency'].strip() for t in attributable):
        reasons.append('missing_currency')
    if any(t.get('source_complete') is not True for t in attributable):
        reasons.append('incomplete_source')
    if len(currencies) > 1:
        reasons.append('mixed_currency')
    if not attributable:
        reasons.append('no_attributable_tasks')
    cost_total = sum(t['cost'] for t in priced) if not reasons else None
    resolved = sum(t.get('outcome') == 'resolved_with_evidence' for t in attributable)
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    coverage = _coverage(len(priced), total)
    common = {'currency': currency, 'coverage': coverage,
              'attributable_tasks': len(attributable),
              'excluded_uncertain_tasks': total - len(attributable), 'unknown_reasons': reasons}
    metrics['cost_total'] = dict(common, value=cost_total)
    metrics['cost_per_resolved_task'] = dict(
        common, numerator=cost_total, denominator=resolved,
        unknown_reasons=reasons + (['no_resolved_tasks'] if not resolved else []),
        value=cost_total / resolved if resolved and cost_total is not None else None)
    metrics['tokens'] = _distribution([t.get('tokens') for t in certain], total)
    metrics['interventions'] = {}
    for kind in sorted({kind for t in tasks for kind in t.get('interventions', {})}):
        counts = [t.get('interventions', {}).get(kind, 0) for t in certain]
        metrics['interventions'][kind] = {
            'count': sum(counts), 'tasks': _rate(sum(n > 0 for n in counts), len(certain), total)}
    failures = [t.get('action_failure_count', 0) for t in certain]
    metrics['action_failures'] = {
        'count': sum(failures), 'tasks': _rate(sum(n > 0 for n in failures), len(certain), total)}
    metrics['abandonment'] = {
        kind: _rate(sum(t.get('abandonment', 'unknown') == kind for t in tasks), total, total)
        for kind in ('explicit', 'possible', 'right_censored', 'natural_session_end',
                     'unknown', 'not_applicable')}
    return metrics


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _distribution(values, total):
    """Quantis exatos nearest-rank: x[ceil(p*n)-1], inclusive a mediana."""
    values = sorted(v for v in values if _number(v))
    result = {'count': len(values), 'sum': sum(values) if values else None,
              'coverage': _coverage(len(values), total)}
    for name, percentile in [('median', .5), ('p75', .75), ('p90', .9), ('p95', .95)]:
        result[name] = values[math.ceil(percentile * len(values)) - 1] if values else None
    return result
