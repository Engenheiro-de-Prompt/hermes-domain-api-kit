"""Projeção offline por tarefa. Nunca interpreta texto como evento comprovado."""
import html
from contextlib import closing
from collections import Counter
import json
import math
from pathlib import Path
import sqlite3
import os

from analysis import _write, _private_file
from study import canonical, digest

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = 'quality-events-v1'
PIPELINE_VERSION = 'quality-v1'
EVENT_TYPES = {'request', 'attempt', 'delivery', 'resolved', 'unresolved', 'correction',
               'intervention', 'abandoned', 'tool_failure', 'session_end'}
ENUMS = {
    'actor': {'user', 'assistant', 'external', 'human_reviewer', 'tool'},
    'severity': {'baixa', 'media', 'alta', 'critica', 'indeterminada'},
    'correction_type': {'factual', 'instrucao_nao_seguida', 'formato', 'omissao', 'contexto_memoria', 'uso_de_ferramenta', 'permissao_seguranca', 'outro', 'indeterminado'},
    'intervention_type': {'correcao', 'reformulacao', 'esclarecimento', 'aprovacao', 'execucao_manual', 'escalonamento', 'nenhuma_observada', 'indeterminada'},
}
REQUIRED = {'event_id', 'tenant_id', 'source_id', 'session_id', 'task_id', 'event_type', 'timestamp'}
OPTIONAL = {'actor', 'attempt_id', 'correction_type', 'severity', 'intervention_type',
            'agent_id', 'agent_version', 'workflow', 'task_class', 'failure_class',
            'cost', 'currency', 'tokens', 'association_uncertain', 'text', 'source_complete'}


def normalize(events, tenant_id):
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        raise ValueError('tenant_mismatch')
    seen, duplicates = {}, 0
    for e in events:
        if not isinstance(e, dict) or not REQUIRED <= set(e) or set(e) - REQUIRED - OPTIONAL:
            raise ValueError('invalid_event')
        if e['tenant_id'] != tenant_id:
            raise ValueError('tenant_mismatch')
        if any(not isinstance(e[k], str) or not e[k] or len(e[k]) > 512
               for k in ('event_id', 'tenant_id', 'source_id', 'session_id')):
            raise ValueError('invalid_event')
        if e['task_id'] is not None and (not isinstance(e['task_id'], str) or not e['task_id'] or len(e['task_id']) > 512):
            raise ValueError('invalid_event')
        if not isinstance(e['event_type'], str) or e['event_type'] not in EVENT_TYPES:
            raise ValueError('invalid_event')
        if e['timestamp'] is not None and (type(e['timestamp']) not in (int, float) or not math.isfinite(e['timestamp'])):
            raise ValueError('invalid_event')
        for k in ('association_uncertain', 'source_complete'):
            if k in e and type(e[k]) is not bool:
                raise ValueError('invalid_event')
        if 'tokens' in e and e['tokens'] is not None and (type(e['tokens']) is not int or e['tokens'] < 0):
            raise ValueError('invalid_event')
        if e.get('cost') is not None and (type(e['cost']) not in (int, float) or not math.isfinite(e['cost']) or e['cost'] < 0
                    or not isinstance(e.get('currency'), str) or len(e['currency']) != 3 or not e['currency'].isascii() or not e['currency'].isupper()):
            raise ValueError('invalid_event')
        for k in ('actor', 'attempt_id', 'correction_type', 'severity', 'intervention_type',
                  'agent_id', 'agent_version', 'workflow', 'task_class', 'failure_class'):
            if k in e and (not isinstance(e[k], str) or not e[k] or len(e[k]) > 512):
                raise ValueError('invalid_event')
        if any(k in e and e[k] not in allowed for k, allowed in ENUMS.items()):
            raise ValueError('invalid_event')
        if 'text' in e and (not isinstance(e['text'], str) or len(e['text']) > 2 * 1024 * 1024):
            raise ValueError('invalid_event')
        identity = (e['source_id'], e['event_id'])
        if identity in seen:
            if seen[identity] != e:
                raise ValueError('event_identity_conflict')
            duplicates += 1
        else:
            seen[identity] = dict(e)
    return list(seen.values()), duplicates


def from_selected(snapshot, *, tenant_id, source_id):
    """Adapter de snapshot selecionado; vínculo por tarefa permanece desconhecido."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get('items'), list):
        raise ValueError('invalid_snapshot')
    events = []
    for item in snapshot['items']:
        if item.get('kind') not in ('task', 'feedback'):
            continue
        refs = item.get('provenance', [])
        if not refs or any(not isinstance(r, dict) or not r.get('session_id') or 'message_id' not in r for r in refs):
            raise ValueError('invalid_snapshot')
        for ref in refs:
            events.append({'event_id': str(ref['message_id']), 'tenant_id': tenant_id,
                           'source_id': source_id, 'session_id': ref['session_id'], 'task_id': None,
                           'event_type': 'intervention', 'intervention_type': 'indeterminada',
                           'timestamp': ref.get('timestamp'), 'actor': 'user',
                           'association_uncertain': True, 'source_complete': False,
                           'text': item['text']})
    # task+feedback may represent the same physical event: normalize below dedups.
    return normalize(events, tenant_id)[0]


def evaluate(events, *, tenant_id, as_of=None, inactivity_seconds=None):
    events, duplicates = normalize(events, tenant_id)
    if as_of is not None and (type(as_of) not in (int, float) or not math.isfinite(as_of)):
        raise ValueError('invalid_observation_window')
    inactivity_seconds = {} if inactivity_seconds is None else inactivity_seconds
    if not isinstance(inactivity_seconds, dict) or any(not isinstance(k, str) or type(v) not in (int, float)
            or not math.isfinite(v) or v <= 0 for k, v in inactivity_seconds.items()):
        raise ValueError('invalid_observation_window')
    if as_of is not None and any(e['timestamp'] is not None and e['timestamp'] > as_of for e in events):
        raise ValueError('events_after_observation_window')
    groups = {}
    for e in events:
        key = (e['source_id'], 'explicit', e['task_id']) if e['task_id'] else (e['source_id'], 'uncertain_session', e['session_id'])
        groups.setdefault(key, []).append(e)
    tasks = []
    for key, values in sorted(groups.items()):
        values = sorted(values, key=lambda e: (e['timestamp'] is None, e['timestamp'] or 0, e['event_id']))
        uncertain = key[1] != 'explicit' or any(e.get('association_uncertain', False) for e in values)
        complete = all(e.get('source_complete', False) for e in values)
        dated = all(e['timestamp'] is not None for e in values)
        starts = [e for e in values if e['event_type'] == 'request']
        attempts = [e for e in values if e['event_type'] == 'attempt']
        resolutions = [e for e in values if e['event_type'] == 'resolved' and e.get('actor') in ('user', 'external', 'human_reviewer')]
        corrections = [e for e in values if e['event_type'] == 'correction' and e.get('actor') in ('user', 'human_reviewer')]
        resolution = resolutions[-1] if resolutions and not uncertain else None
        # A later repair/reopen invalidates the earlier terminal claim.
        later_repair = resolution and any(e['event_type'] in ('correction', 'attempt', 'unresolved')
                        and (e['timestamp'] is None or resolution['timestamp'] is None or e['timestamp'] >= resolution['timestamp'])
                        for e in values if e is not resolution)
        if later_repair:
            resolution = None
        negatives = [e for e in values if e['event_type'] == 'unresolved' and e.get('actor') in ('user', 'external', 'human_reviewer')]
        terminal = resolution or (negatives[-1] if negatives and not uncertain else None)
        if terminal and any(e['event_type'] in ('attempt', 'correction') and
                (e['timestamp'] is None or terminal['timestamp'] is None or e['timestamp'] >= terminal['timestamp']) for e in values):
            terminal = None
        attempt_ids = [e.get('attempt_id') for e in attempts]
        observable = (not uncertain and complete and dated and len(starts) == 1 and bool(attempts)
                      and all(attempt_ids) and len(set(attempt_ids)) == len(attempt_ids)
                      and terminal is not None and terminal.get('attempt_id') in attempt_ids
                      and starts[0]['timestamp'] < attempts[0]['timestamp'] < terminal['timestamp'])
        first = bool(resolution and len(attempts) == 1 and resolution.get('attempt_id') == attempt_ids[0] and not corrections) if observable else None
        duration = (resolution['timestamp'] - starts[0]['timestamp']
                    if resolution and len(starts) == 1 and starts[0]['timestamp'] is not None
                    and resolution['timestamp'] is not None and resolution['timestamp'] >= starts[0]['timestamp'] else None)
        abandonment = 'not_applicable' if resolution else 'unknown'
        if not resolution and not uncertain:
            activity = [e for e in values if e['event_type'] not in ('abandoned', 'session_end')]
            # Encerramentos históricos não descrevem uma tarefa retomada.
            endings = [e for e in values if e['event_type'] in ('abandoned', 'session_end')
                       and e['timestamp'] is not None
                       and all(a['timestamp'] is not None and a['timestamp'] < e['timestamp']
                               for a in activity)]
            if any(e['event_type'] == 'abandoned' and e.get('actor') in ('user', 'human_reviewer') for e in endings):
                abandonment = 'explicit'
            elif any(e['event_type'] == 'session_end' for e in endings):
                abandonment = 'natural_session_end'
            elif dated and as_of is not None:
                window = inactivity_seconds.get(values[0].get('workflow', 'default'))
                if window is not None:
                    abandonment = 'possible' if as_of - values[-1]['timestamp'] >= window else 'right_censored'
        billable = [e for e in values if e['event_type'] == 'attempt' or e.get('cost') is not None or e.get('tokens') is not None]
        currencies = {e.get('currency') for e in billable}
        cost = (sum(e['cost'] for e in billable) if billable and complete and not uncertain
                and all(e.get('cost') is not None for e in billable) and len(currencies) == 1 else None)
        tokens = (sum(e['tokens'] for e in billable) if billable and complete and not uncertain
                  and all(e.get('tokens') is not None for e in billable) else None)
        dimensions = {}
        for name in ('agent_id', 'agent_version', 'workflow', 'task_class'):
            distinct = {e[name] for e in values if name in e}
            dimensions[name] = next(iter(distinct)) if len(distinct) == 1 else None
        tasks.append({**dimensions, 'task_id': digest([tenant_id, key]),
                      'tenant_id': tenant_id, 'source_id': key[0],
                      'session_ids': sorted({e['session_id'] for e in values}),
                      'start_timestamp': starts[0]['timestamp'] if len(starts) == 1 else None,
                      'correction_classes': sorted({e.get('failure_class', e.get('correction_type', 'indeterminado')) for e in corrections}),
                      'correction_types': dict(Counter(e.get('correction_type', 'indeterminado') for e in corrections)),
                      'correction_severities': dict(Counter(e.get('severity', 'indeterminada') for e in corrections)), 'source_event_ids': [e['event_id'] for e in values],
                      'outcome': 'resolved_with_evidence' if resolution else ('unresolved' if terminal else 'unknown'), 'satisfaction': 'unknown',
                      'association_uncertain': uncertain, 'source_complete': complete, 'abandonment': abandonment,
                      'unknown_reason': None if observable else 'insufficient_task_attempt_or_outcome_evidence',
                      'first_attempt_resolved': first, 'resolution_seconds': duration,
                      'cost': cost, 'currency': next(iter(currencies)) if cost is not None else None, 'tokens': tokens,
                      'cost_unknown_reason': None if cost is not None else 'incomplete_attribution_or_currency',
                      'correction_count': len(corrections), 'extra_attempts': max(0, len(attempts) - 1) if complete and not uncertain and attempts else None,
                      'interventions': dict(Counter(e.get('intervention_type', 'indeterminada') for e in values
                                                  if e['event_type'] == 'intervention' and e.get('actor') in ('user', 'human_reviewer'))),
                      'action_failure_count': sum(e['event_type'] == 'tool_failure' for e in values)})
    report = {'schema_version': SCHEMA_VERSION, 'pipeline_version': PIPELINE_VERSION,
              'total_tasks': len(tasks), 'coverage': {'duplicate_events': duplicates, 'unique_events': len(events), 'missing_task_id': sum(e['task_id'] is None for e in events), 'missing_timestamp': sum(e['timestamp'] is None for e in events)},
              'limitations': ['Sem validação humana do classificador; ausência de correção não mede satisfação.']}
    from quality_metrics import aggregate
    report['metrics'] = aggregate(tasks)
    report['coverage']['fields'] = {
        name: {'present': sum(e.get(name) is not None for e in events), 'total': len(events)}
        for name in sorted(REQUIRED | (OPTIONAL - {'text'}))}
    report['coverage']['partial_source_events'] = sum(not e.get('source_complete', False) for e in events)
    return tasks, report


def _display_metric(value):
    if not isinstance(value, dict):
        return 'Não mensurável' if value is None else str(value)
    if 'numerator' in value and 'denominator' in value:
        result = str(value['numerator']) + ' / ' + str(value['denominator'])
        result += (' — ' + format(value['value'], '.1%')) if value.get('value') is not None else ' — Não mensurável'
        interval = value.get('wilson95')
        if interval:
            result += '; Wilson 95%: ' + format(interval['lower'], '.1%') + '–' + format(interval['upper'], '.1%')
    elif 'median' in value:
        result = '; '.join(name + ': ' + ('Não mensurável' if value[name] is None else str(value[name])) for name in ('median', 'p75', 'p90', 'p95'))
        result += '; soma conhecida: ' + str(value['sum'])
    elif 'value' in value:
        result = 'Não mensurável' if value['value'] is None else str(value['value']) + ' ' + str(value.get('currency') or '')
    else:
        return '\n'.join(k + ': ' + _display_metric(v) for k, v in value.items()) or 'Nenhuma observação nesta seleção'
    coverage = value.get('coverage')
    if coverage:
        result += '; cobertura ' + str(coverage['known']) + ' / ' + str(coverage['total'])
    if value.get('unknown_reasons'):
        result += '; motivo: ' + ', '.join(value['unknown_reasons'])
    return result


def render(report, tasks=()):
    """HTML executivo agregado; projeção allowlisted sem textos de eventos."""
    from quality_story import build
    from quality_dashboard import render as render_dashboard
    return render_dashboard(build(report, tasks))


def execute(args, *, validation_controls=None):
    import cli
    if not args.input or not args.tenant or not args.work:
        raise ValueError('quality_input_required')
    from api_client import _unique_object, _reject_constant
    source = Path(args.input).expanduser().absolute()
    if any(p.is_symlink() for p in (source, *source.parents)):
        raise ValueError('invalid_quality_input')
    with source.open('rb') as stream:
        raw = stream.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError('quality_input_too_large')
    data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1 or not {'events'} <= set(data) or set(data) - {'schema_version', 'events', 'as_of', 'inactivity_seconds'}:
        raise ValueError('invalid_quality_input')
    normalized, _duplicates = normalize(data['events'], args.tenant)
    estimated_calls = sum(((len(e['text']) + 2399) // 2400) *
                          (int(e.get('actor') == 'user') + int(e.get('actor') == 'assistant' or e['event_type'] == 'delivery'))
                          for e in normalized if e.get('text', '').strip())
    if args.command == 'quality-analyze' and (args.max_classifier_calls < 1 or estimated_calls > args.max_classifier_calls):
        raise ValueError('classifier_budget_exceeded')
    tasks, report = evaluate(data['events'], tenant_id=args.tenant, as_of=data.get('as_of'), inactivity_seconds=data.get('inactivity_seconds'))
    requested = Path(args.work).expanduser().absolute()
    if any(p.is_symlink() for p in (requested, *requested.parents)):
        raise ValueError('invalid_work')
    work = cli.private_work(args.work) / 'quality'
    if work.is_symlink():
        raise ValueError('invalid_work')
    work.mkdir(mode=0o700, exist_ok=True)
    os.chmod(work, 0o700)
    manifest = {'schema_version': SCHEMA_VERSION, 'pipeline_version': PIPELINE_VERSION,
                'extractor_version': EXTRACTOR_VERSION, 'input_sha256': digest(data),
                'tenant_sha256': digest(args.tenant)}
    run_id = digest(manifest)
    manifest['pipeline_run_id'] = run_id
    lock_existed = os.path.lexists(work / 'lock.sqlite')
    _private_file(work / 'lock.sqlite')
    with closing(sqlite3.connect(work / 'lock.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        mp = work / 'manifest.json'
        names = ('tasks.jsonl', 'report.json', 'dashboard.html', 'narrative.json')
        if mp.is_symlink():
            raise ValueError('invalid_output')
        previous = None
        if mp.exists():
            try:
                previous = json.loads(mp.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                raise ValueError('checkpoint_incomplete') from None
            if not isinstance(previous, dict) or ('classification_started' in previous and type(previous['classification_started']) is not bool):
                raise ValueError('checkpoint_incomplete')
            if {k: v for k, v in previous.items() if k not in ('classification_started', 'validation_controls', 'validation_controls_sha256')} != manifest:
                raise ValueError('campaign_mismatch')
        elif lock_existed or any(os.path.lexists(work / name) for name in names):
            raise ValueError('checkpoint_incomplete')
        else:
            _write(mp, canonical(dict(manifest, classification_started=False)) + '\n')
        label_path = work / 'labels.json'
        labels = []
        checkpoints = work / 'classification'
        coordinator = work / 'classification-manifest.json'
        started = bool(previous and previous.get('classification_started')) or os.path.lexists(label_path) or os.path.lexists(checkpoints) or os.path.lexists(coordinator)
        if args.command == 'quality-analyze':
            legacy_unproven = previous is not None and 'classification_started' not in previous and not started
            if estimated_calls and (started or legacy_unproven) and (not checkpoints.is_dir() or not coordinator.is_file()):
                raise ValueError('checkpoint_incomplete')
        state: dict[str, object] = dict(manifest, classification_started=bool(started and estimated_calls))
        if previous and ('validation_controls' in previous or 'validation_controls_sha256' in previous):
            frozen = previous.get('validation_controls')
            if not isinstance(frozen, dict) or digest(frozen) != previous.get('validation_controls_sha256'):
                raise ValueError('snapshot_integrity_failed')
            if validation_controls is not None and validation_controls != frozen:
                raise ValueError('campaign_mismatch')
            validation_controls = frozen
        elif validation_controls is None:
            from quality_smoke import restore_legacy_controls
            validation_controls = restore_legacy_controls(work, manifest['input_sha256'])
        if validation_controls is not None:
            if validation_controls.get('sample_sha256') != manifest['input_sha256']:
                raise ValueError('campaign_mismatch')
            state.update(validation_controls=validation_controls, validation_controls_sha256=digest(validation_controls))
        if previous != state:
            _write(mp, canonical(state) + '\n')
        if args.command == 'quality-analyze':
            from quality_classifier import classify_events
            client = cli.configured_client(args)
            model = cli.select_model(client, args.model)
            if estimated_calls:
                state['classification_started'] = True
                _write(mp, canonical(state) + '\n')
            normalized = normalize(data['events'], args.tenant)[0]
            labels = classify_events(normalized, client, model, work / 'classification',
                                     checkpoint_manifest=work / 'classification-manifest.json')
            _write(label_path, canonical({'input_sha256': manifest['input_sha256'], 'labels': labels, 'labels_sha256': digest(labels)}) + '\n')
        elif os.path.lexists(label_path):
            _private_file(label_path)
            cached = json.loads(label_path.read_text(encoding='utf-8'))
            if cached.get('input_sha256') != manifest['input_sha256'] or digest(cached.get('labels')) != cached.get('labels_sha256'):
                raise ValueError('snapshot_integrity_failed')
            labels = cached['labels']
        # Event IDs only link inferences to tasks; they never alter deterministic facts.
        for task in tasks:
            task.update({'schema_version': SCHEMA_VERSION, 'extractor_version': EXTRACTOR_VERSION,
                         'pipeline_run_id': run_id, 'classifications': [label for label in labels
                         if label['source_id'] == task['source_id'] and label['event_id'] in task['source_event_ids']]})
        report['classifier'] = {
            'mode': 'classified' if args.command == 'quality-analyze' else 'offline',
            'estimated_full_campaign_calls': estimated_calls, 'max_calls_budget': args.max_classifier_calls,
            'eligible_event_labels': sum((int(e.get('actor') == 'user') + int(e.get('actor') == 'assistant' or e['event_type'] == 'delivery')) for e in normalized if e.get('text', '').strip()),
            'labels': len(labels), 'review_required': sum(l['review_required'] for l in labels),
            'indeterminate': sum(l['label_value'] in ('indeterminado', 'indeterminada') for l in labels),
            'failed': sum(l['unknown_reason'] == 'classification_failed' for l in labels),
            'score_type': 'model_class_distribution_uncalibrated', 'semantic_qualification': 'not_established',
            'monetary_cost': None, 'cost_unknown_reason': 'classifier_billing_telemetry_not_available',
            'models': sorted({l['model_id'] for l in labels}),
            'distribution': dict(Counter(l['label_name'] + ':' + l['label_value'] for l in labels)),
        }
        if validation_controls is not None:
            from quality_smoke import summarize
            verification = summarize(labels, validation_controls, report['classifier']['models'])
            report['validation'] = {key: value for key, value in verification.items() if key != 'checks'}
            _write(work / 'smoke-result.json', canonical(verification) + '\n')
        report['pipeline_run_id'] = run_id
        timestamps = [e['timestamp'] for e in normalized if e['timestamp'] is not None]
        report['observation'] = {'source_scope': 'synthetic_declared' if normalized and all(e['source_id'] in ('synthetic_fixture', 'synthetic_control', 'synthetic-controls-v1') for e in normalized) else 'provided_events',
                                 'first_event_timestamp': min(timestamps) if timestamps else None,
                                 'last_event_timestamp': max(timestamps) if timestamps else None,
                                 'as_of': data.get('as_of')}
        from quality_story import build, VERSION as NARRATIVE_VERSION
        from quality_dashboard import render as render_dashboard
        story = build(report, tasks)
        report['narrative_version'] = NARRATIVE_VERSION
        _write(work / 'narrative.json', canonical(story) + '\n')
        _write(work / 'tasks.jsonl', ''.join(canonical(t) + '\n' for t in tasks))
        _write(work / 'report.json', canonical(report) + '\n')
        _write(work / 'dashboard.html', render_dashboard(story))
    print(canonical(report))
    return 0
