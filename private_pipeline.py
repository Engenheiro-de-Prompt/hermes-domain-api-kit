"""RAM-only analysis; saves deliberately retained aggregates, never payloads."""
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import analysis
from api_client import _unique_object, _reject_constant, privacy_destination
from study import canonical

_FREE_TEXT_DIMENSIONS = {'agent_id', 'agent_version', 'workflow', 'task_class', 'failure_class'}


def _destination(args):
    privacy_destination(args.base_url)
    if not args.work:
        raise ValueError('explicit_work_required')
    output = Path(args.work).expanduser().absolute()
    if '..' in output.parts:
        raise ValueError('invalid_work')
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('invalid_work')
    repo = Path(__file__).resolve().parent
    if output == repo or repo in output.parents:
        raise ValueError('work_must_be_outside_repository')
    if output.exists():
        raise ValueError('private_output_exists')
    if args.home:
        home = Path(args.home).expanduser().absolute()
        if '..' in home.parts:
            raise ValueError('invalid_work')
        home = home.resolve()
        if output == home or home in output.parents or output in home.parents:
            raise ValueError('invalid_work')
    return output


def _collect(args):
    from extractor import _redact
    from quality import from_selected, normalize
    if bool(args.home) == bool(args.input) or args.input and not args.tenant:
        raise ValueError('private_source_required')
    if args.limit is not None or args.rubric != 'domain':
        raise ValueError('selection_invalid')
    if args.input:
        if args.session or args.sources or args.context_chars != 1200 or args.delegation != 'human':
            raise ValueError('selection_invalid')
        source = Path(args.input).expanduser().absolute()
        if any(p.is_symlink() for p in (source, *source.parents)):
            raise ValueError('invalid_quality_input')
        with source.open('rb') as stream:
            raw = stream.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError('quality_input_too_large')
        try:
            data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if (not isinstance(data, dict) or data.get('schema_version') != 1
                    or set(data) - {'schema_version', 'events', 'as_of'}
                    or not isinstance(data.get('events'), list)):
                raise ValueError()
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError('invalid_quality_input') from None
        events, _ = normalize(data['events'], args.tenant)
        for event in events:
            if 'text' in event:
                event['text'] = _redact(event['text'])
        items = []
        for i, event in enumerate(events):
            if event.get('actor') != 'user' or not event.get('text', '').strip():
                continue
            for kind in ('task', 'feedback'):
                items.append({'id': kind + '_' + str(i), 'kind': kind, 'text': event['text'],
                              'context': '', 'context_missing': True, 'context_truncated': False,
                              'provenance': [{'session_id': event['session_id'], 'message_id': event['event_id'], 'timestamp': event['timestamp']}]})
        return items, events, args.tenant, data.get('as_of'), {'status': 'provided_events', 'source_counts': {'events': len(events)}, 'failure_count': 0}
    from selection import extract_selected
    if args.tenant:
        raise ValueError('selection_invalid')
    selected = extract_selected(args.home, sources=args.sources or ('tasks', 'feedback', 'skills', 'memories'),
                                session_ids=args.session, delegation=args.delegation, context_chars=args.context_chars)
    coverage = selected['coverage']
    if coverage.get('status') != 'ok':
        raise ValueError('incomplete_corpus')
    tenant = 'selected_profile'
    events = from_selected(selected, tenant_id=tenant, source_id='selected_profile')
    safe_coverage = {'status': coverage['status'], 'source_counts': coverage['source_counts'],
                     'failure_count': len(coverage.get('failures', []))}
    return selected['items'], events, tenant, None, safe_coverage


def _plans(items, events):
    plans = []
    for name in ('domain', 'satisfaction', 'corrections'):
        rubric = analysis.load_rubric(name)
        plans.append((name, rubric, [i for i in items if i['kind'] in rubric['kinds']]))
    for name, kind in (('quality_correction', 'feedback'), ('quality_outcome', 'task')):
        rubric = analysis.load_rubric(Path(__file__).parent / 'rubrics' / (name + '.json'))
        eligible = []
        for index, event in enumerate(events):
            allowed = event.get('actor') == 'user' if kind == 'feedback' else event.get('actor') == 'assistant' or event['event_type'] == 'delivery'
            if allowed and event.get('text', '').strip():
                eligible.append({'id': str(index), 'kind': kind, 'text': event['text'],
                                 'context': '', 'context_missing': True, 'context_truncated': False})
        plans.append((name, rubric, eligible))
    return plans


def _quality(events, tenant, as_of, labels, planned, *, model=None):
    from quality import evaluate
    # Free-form dimensions are suppressed, not copied into aggregates or segments.
    projected = [{k: v for k, v in event.items() if k not in _FREE_TEXT_DIMENSIONS} for event in events]
    tasks, report = evaluate(projected, tenant_id=tenant, as_of=as_of)
    inferred = []
    for rubric, label_name in (('quality_correction', 'explicit_user_correction'), ('quality_outcome', 'outcome')):
        for row in labels[rubric]:
            event = events[int(row['id'])]
            inferred.append({'source_id': event['source_id'], 'event_id': event['event_id'],
                             'label_name': label_name, 'label_value': row['label'],
                             'review_required': True, 'is_observable': False,
                             'unknown_reason': 'classification_failed' if row['status'] != 'ok' else 'ephemeral_score_not_retained'})
    for task in tasks:
        task['classifications'] = [l for l in inferred if l['source_id'] == task['source_id'] and l['event_id'] in task['source_event_ids']]
    report['classifier'] = {
        'mode': 'classified' if inferred else 'offline', 'labels': len(inferred),
        'review_required': len(inferred), 'indeterminate': sum(l['label_value'] in ('indeterminado', 'indeterminada') for l in inferred),
        'failed': sum(l['unknown_reason'] == 'classification_failed' for l in inferred),
        'estimated_full_campaign_calls': planned, 'eligible_event_labels': len(inferred),
        'score_type': 'not_retained', 'semantic_qualification': 'not_established',
        'monetary_cost': None, 'models': [model] if inferred and model else [],
        'distribution': dict(Counter(l['label_name'] + ':' + l['label_value'] for l in inferred))}
    timestamps = [e['timestamp'] for e in events if e['timestamp'] is not None]
    def day(stamp):
        return datetime.fromtimestamp(stamp, timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    report['observation'] = {'source_scope': 'provided_events', 'first_event_timestamp': day(min(timestamps)) if timestamps else None,
                             'last_event_timestamp': day(max(timestamps)) if timestamps else None, 'as_of': None}
    return tasks, report


def _save(output, files):
    old = os.umask(0o077)
    try:
        output.mkdir(parents=True, mode=0o700, exist_ok=False)
        os.chmod(output, 0o700)
        if os.name == 'posix' and output.stat().st_mode & 0o077:
            raise ValueError('insecure_output_permissions')
        for name, body in files.items():
            # New exclusive private directory; the reusable helper rejects links/hardlinks.
            analysis._write(output / name, body)
    finally:
        os.umask(old)


def execute(args):
    import cli
    from ephemeral_analysis import classify, plan_calls
    from ephemeral_feedback import build as feedback_build
    from feedback_dashboard import render as feedback_render
    from feedback_pipeline import _cutoff
    from quality_story import build as story_build
    from quality_dashboard import render as quality_render
    output = _destination(args)
    cutoff = _cutoff(args.cutoff)
    # Validate calendar before API/key; UTC needs no optional timezone package.
    from feedback_report import _timezone
    _timezone(args.timezone)
    if type(args.max_classifier_calls) is not int or args.max_classifier_calls < 0:
        raise ValueError('classifier_budget_exceeded')
    items, events, tenant, as_of, coverage = _collect(args)
    from feedback_report import _date
    dates = [_date(item, timezone_name=args.timezone) for item in items if item.get('kind') == 'feedback']
    dates = [day for day in dates if day is not None]
    if dates and max(dates) > cutoff:
        raise ValueError('selection_invalid')
    plans = _plans(items, events)
    planned = sum(plan_calls(rows, rubric) for _, rubric, rows in plans)
    if planned > args.max_classifier_calls and not args.dry_run:
        raise ValueError('classifier_budget_exceeded')
    # Validate event chronology before an irreversible external request.
    _quality(events, tenant, as_of, {'quality_correction': [], 'quality_outcome': []}, planned)
    if args.dry_run:
        print(canonical({'mode': 'private-plan', 'estimated_classifier_calls': planned,
                         'max_classifier_calls': args.max_classifier_calls,
                         'budget_sufficient': planned <= args.max_classifier_calls,
                         'source_counts': coverage['source_counts'],
                         'network_used': False, 'payload_files_written': False,
                         'output_created': False, 'not_an_api_healthcheck': True}))
        return 0
    client = cli.configured_client(args) if planned else None
    model = cli.select_model(client, args.model) if client else None
    labels = {name: classify(rows, client, model, rubric=rubric, max_calls=args.max_classifier_calls) if rows else []
              for name, rubric, rows in plans}
    if client is not None and client.privacy_failure is not None:
        from api_client import ClientError
        raise ClientError(client.privacy_failure)
    feedback = feedback_build(items, labels, timezone_name=args.timezone)
    feedback['observed_history'] = {'scope': 'selected_history_only',
        'first_date': str(min(dates)) if dates else None, 'last_date': str(max(dates)) if dates else None,
        'installation_date_proven': False, 'source_status': 'ok',
        'source_failure_count': coverage['failure_count']}
    tasks, quality = _quality(events, tenant, as_of, labels, planned, model=model)
    story = story_build(quality, tasks)
    failed = sum(row['status'] != 'ok' for rows in labels.values() for row in rows)
    rubric_counts = {name: {'items': len(rows), 'failed': sum(row['status'] != 'ok' for row in rows),
                            'distribution': dict(Counter(row['label'] for row in rows))} for name, rows in labels.items()}
    remote = privacy_destination(args.base_url).scheme == 'https'
    privacy = {'version': 1, 'mode': 'memory_only_payloads', 'payload_files_written': False,
               'checkpoints': False, 'automatic_retry': False, 'async_idle_queue': False,
               'network_used': bool(planned), 'transport': 'https_certificate_verified' if remote else 'http_loopback_only',
               'remote_deletion_header_checked': bool(planned and remote), 'no_store_response_required': bool(planned),
               'saved_content': 'deliberately_retained_aggregates_only', 'aggregates_are_anonymous': False,
               'original_history_deleted': False, 'physical_erasure_guaranteed': False,
               'python_memory_zeroization_guaranteed': False, 'os_swap_dumps_backups_audited': False,
               'end_to_end_encryption_guaranteed': False, 'upstream_database_independently_verified': False}
    from study import digest
    contract = {'version': 1, 'model_id': model,
                'rubrics': [{'id': r['id'], 'version': r['version'], 'sha256': digest(r)} for _, r, _ in plans],
                'timezone': args.timezone, 'context_chars': min(args.context_chars, 1200),
                'sources': args.sources or (['provided_events'] if args.input else ['tasks', 'feedback', 'skills', 'memories']),
                'delegation': args.delegation, 'session_filter_count': len(args.session),
                'history_identity_stored': False, 'cross_run_merge_supported': False}
    report = {'version': 1, 'mode': 'private-analyze', 'analysis_contract': contract, 'planned_classifier_calls': planned,
              'classification_failures': failed, 'selection_coverage': coverage,
              'rubrics': rubric_counts, 'feedback': feedback, 'quality': quality, 'privacy': privacy}
    files = {'report.json': canonical(report) + '\n', 'narrative.json': canonical(story) + '\n',
             'privacy.json': canonical(privacy) + '\n', 'dashboard.html': quality_render(story),
             'feedback.html': feedback_render(feedback, cutoff)}
    _save(output, files)
    print(canonical({'mode': 'private-analyze', 'output': str(output), 'planned_classifier_calls': planned,
                     'classification_failures': failed, 'payload_files_written': False}))
    return 1 if failed else 0


def check(args):
    import cli
    privacy_destination(args.base_url)
    client = cli.configured_client(args)
    model = cli.select_model(client, args.model)
    print(canonical({'privacy_preflight': 'passed', 'model': model, 'scope': 'immediate_api_response_headers_only',
                     'history_read': False, 'classification_sent': False,
                     'not_proof_of_physical_erasure': True}))
    return 0
