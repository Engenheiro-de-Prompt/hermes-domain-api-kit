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
    if output.exists() and not args.resume:
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
        import hashlib
        return items, events, args.tenant, data.get('as_of'), {'status': 'provided_events', 'source_counts': {'events': len(events)}, 'failure_count': 0}, hashlib.sha256(raw).hexdigest()
    from selection import extract_selected
    if args.tenant:
        raise ValueError('selection_invalid')
    import hashlib
    identity = hashlib.sha256()
    def snapshot(value):
        encoded = canonical(value).encode('utf-8')
        identity.update(len(encoded).to_bytes(8, 'big'))
        identity.update(encoded)
    selected = extract_selected(args.home, sources=args.sources or ('tasks', 'feedback', 'skills', 'memories'),
                                session_ids=args.session, delegation=args.delegation, context_chars=args.context_chars,
                                snapshot=snapshot)
    coverage = selected['coverage']
    if coverage.get('status') != 'ok':
        raise ValueError('incomplete_corpus')
    tenant = 'selected_profile'
    events = from_selected(selected, tenant_id=tenant, source_id='selected_profile')
    safe_coverage = {'status': coverage['status'], 'source_counts': coverage['source_counts'],
                     'failure_count': len(coverage.get('failures', []))}
    return selected['items'], events, tenant, None, safe_coverage, identity.hexdigest()


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
        'review_required': len(inferred), 'indeterminate': sum(l['unknown_reason'] != 'classification_failed' and l['label_value'] in ('indeterminado', 'indeterminada') for l in inferred),
        'failed': sum(l['unknown_reason'] == 'classification_failed' for l in inferred),
        'estimated_full_campaign_calls': planned, 'eligible_event_labels': len(inferred),
        'score_type': 'not_retained', 'semantic_qualification': 'not_established',
        'monetary_cost': None, 'models': [model] if inferred and model else [],
        'distribution': dict(Counter(l['label_name'] + ':' + l['label_value'] for l in inferred if l['unknown_reason'] != 'classification_failed'))}
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
        from private_checkpoint import atomic_text, sync_directory
        for name, body in files.items():
            atomic_text(output / name, body)
        sync_directory(output.parent)
    finally:
        os.umask(old)


def execute(args):
    from contextlib import ExitStack
    with ExitStack() as cleanup:
        return _execute(args, cleanup)


def _execute(args, cleanup):
    import cli
    from ephemeral_analysis import classify, plan_calls
    from ephemeral_feedback import build as feedback_build
    from feedback_dashboard import render as feedback_render
    from feedback_pipeline import _cutoff
    from quality_story import build as story_build
    from quality_dashboard import render as quality_render
    import math
    retry = getattr(args, 'retry_transient', False)
    recover = getattr(args, 'recover_uncertain', False)
    retry_attempts = getattr(args, 'retry_attempts', 6)
    retry_backoff = getattr(args, 'retry_backoff', 1)
    if (type(retry_attempts) is not int or not 1 <= retry_attempts <= 100
            or type(retry_backoff) not in (int, float) or not math.isfinite(retry_backoff)
            or not 0 <= retry_backoff <= 60
            or recover and not (retry and args.resume)
            or retry and args.ram_only
            or not retry and (retry_attempts != 6 or retry_backoff != 1)):
        raise ValueError('invalid_retry_policy')
    output = _destination(args)
    cutoff = _cutoff(args.cutoff)
    # Validate calendar before API/key; UTC needs no optional timezone package.
    from feedback_report import _timezone
    _timezone(args.timezone)
    if args.max_classifier_calls is not None and (type(args.max_classifier_calls) is not int or args.max_classifier_calls < 0):
        raise ValueError('classifier_budget_exceeded')
    # An input file is identified by ALL bytes (including fields redaction omits).
    # Re-read around collection, fail closed on replacement/mutation; never copy it.
    from study import digest
    import hashlib
    def source_identity():
        if args.input:
            path = Path(args.input).expanduser().absolute()
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('invalid_quality_input')
            with path.open('rb') as stream:
                before = os.fstat(stream.fileno())
                raw = stream.read(16 * 1024 * 1024 + 1)
                after = os.fstat(stream.fileno())
            # Reading may legitimately update atime. Only identity, ownership,
            # size and mutation timestamps belong to the snapshot guard.
            def stable_stat(value):
                return tuple(getattr(value, key) for key in (
                    'st_dev', 'st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                    'st_size', 'st_mtime_ns', 'st_ctime_ns'))
            if (len(raw) > 16 * 1024 * 1024
                    or stable_stat(before) != stable_stat(after)
                    or stable_stat(path.stat()) != stable_stat(after)):
                raise ValueError('snapshot_integrity_failed')
            return hashlib.sha256(raw).hexdigest()
        return None
    source_before = source_identity()
    items, events, tenant, as_of, coverage, collected_identity = _collect(args)
    if args.home and _collect(args) != (items, events, tenant, as_of, coverage, collected_identity):
        raise ValueError('snapshot_integrity_failed')
    if args.input and (source_identity() != source_before or collected_identity != source_before):
        raise ValueError('snapshot_integrity_failed')
    from feedback_report import _date
    dates = [_date(item, timezone_name=args.timezone) for item in items if item.get('kind') == 'feedback']
    dates = [day for day in dates if day is not None]
    if dates and max(dates) > cutoff:
        raise ValueError('selection_invalid')
    plans = _plans(items, events)
    planned = sum(plan_calls(rows, rubric) for _, rubric, rows in plans)
    if args.max_classifier_calls is None:
        args.max_classifier_calls = planned
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
    if args.ram_only and (args.resume or args.checkpoint_dir):
        raise ValueError('selection_invalid')
    journal = None
    if not args.ram_only:
        from private_checkpoint import Journal
        checkpoint = Path(args.checkpoint_dir).expanduser().absolute() if args.checkpoint_dir else output.with_name(output.name + '.checkpoint')
        repo = Path(__file__).resolve().parent
        if ('..' in checkpoint.parts or checkpoint == output or output in checkpoint.parents
                or checkpoint in output.parents or checkpoint == repo or repo in checkpoint.parents):
            raise ValueError('invalid_work')
        if args.home:
            home = Path(args.home).expanduser().resolve()
            if checkpoint == home or home in checkpoint.parents or checkpoint in home.parents:
                raise ValueError('invalid_work')
        frozen = {'source': collected_identity, 'items': items, 'events': events, 'tenant': tenant,
                  'as_of': as_of, 'coverage': coverage, 'home': str(Path(args.home).expanduser().absolute()) if args.home else None,
                  'input_path': str(Path(args.input).expanduser().absolute()) if args.input else None,
                  'rubrics': [r for _, r, _ in plans], 'model': args.model, 'endpoint': args.base_url,
                  'cutoff': str(cutoff), 'timezone': args.timezone, 'sources': args.sources,
                  'session': args.session, 'context': args.context_chars, 'delegation': args.delegation,
                  'budget': args.max_classifier_calls, 'keep_alive': args.keep_alive,
                  'output': str(output), 'pipeline_version': 2, 'chunk_chars': 2400}
        identities = [(name, row, offset) for name, _, rows in plans for row in rows
                      for offset in range(0, len(row['text']), 2400)]
        allowed = [rubric['criteria'] for _, rubric, rows in plans for row in rows
                   for _ in range(0, len(row['text']), 2400)]
        journal = Journal(checkpoint, args.resume, frozen, identities, allowed)
        cleanup.callback(journal.close)
        if journal.done:
            # Totals are NOT reconstructed decisions. Existing exports remain authoritative.
            if not output.is_dir() or not all((output / name).is_file() for name in ('report.json', 'privacy.json', 'narrative.json', 'dashboard.html', 'feedback.html')):
                raise ValueError('incomplete_result_artifacts')
            expected_exports = journal.data.get('exports')
            names = ('report.json', 'privacy.json', 'narrative.json', 'dashboard.html', 'feedback.html')
            if (not isinstance(expected_exports, dict) or set(expected_exports) != set(names)
                    or any((output / name).is_symlink() or hashlib.sha256((output / name).read_bytes()).hexdigest() != expected_exports[name] for name in names)):
                raise ValueError('incomplete_result_artifacts')
            journal.cleanup_completed()
            print(canonical({'mode': 'private-analyze', 'output': str(output),
                             'artifacts': {'dashboard_html': str(output / 'dashboard.html'),
                                           'feedback_html': str(output / 'feedback.html')},
                             'complete': True, 'already_completed': True, 'network_used': False}))
            return 0
    retry_can_resume = False
    if journal is not None and retry and not journal.done:
        unknown = {r['hash'] for r in journal.data['segments'] if r['status'] == 'unknown'}
        retry_can_resume = recover or not (unknown - set(journal.data.get('recovery', {}).get('retryable', [])))
    need_client = planned and (journal is None or
        (not journal.paused or retry_can_resume) and any(r['status'] != 'ok' for r in journal.data['segments']))
    client = cli.configured_client(args) if need_client else None
    model = cli.select_model(client, args.model) if client else args.model
    if journal is not None and client is not None:
        journal.bind_model(model)
    if journal is not None and retry:
        # Enabling legacy replay occurs only AFTER an authenticated catalog and
        # frozen-model match; it never requires hand-editing the checkpoint.
        journal.enable_retry(max_attempts=retry_attempts, backoff=retry_backoff,
                             recover_uncertain=bool(recover and client is not None),
                             progress=cli.progress_report)
    # With automatic model selection, a paused run cannot recover its literal model
    # from the opaque checkpoint; no calls occur and labels remain reconstructable.
    classification_model = model or 'checkpoint-restored'
    labels = {name: classify(rows, client, classification_model, rubric=rubric, max_calls=args.max_classifier_calls, journal=journal) if rows else []
              for name, rubric, rows in plans}
    feedback = feedback_build(items, labels, timezone_name=args.timezone)
    feedback['observed_history'] = {'scope': 'selected_history_only',
        'first_date': str(min(dates)) if dates else None, 'last_date': str(max(dates)) if dates else None,
        'installation_date_proven': False, 'source_status': 'ok',
        'source_failure_count': coverage['failure_count']}
    tasks, quality = _quality(events, tenant, as_of, labels, planned, model=model)
    story = story_build(quality, tasks)
    failed = sum(row['status'] != 'ok' for rows in labels.values() for row in rows)
    rubric_counts = {name: {'items': len(rows), 'failed': sum(row['status'] != 'ok' for row in rows),
                            'distribution': dict(Counter(row['label'] for row in rows if row['status'] == 'ok'))} for name, rows in labels.items()}
    remote = privacy_destination(args.base_url).scheme == 'https'
    privacy = {'version': 1, 'mode': 'memory_only_payloads', 'payload_files_written': False,
               'checkpoints': journal is not None, 'automatic_retry': retry, 'async_idle_queue': False,
               'network_used': client is not None, 'transport': 'https_certificate_verified' if remote else 'http_loopback_only',
               'remote_deletion_header_checked': bool(client is not None and remote), 'no_store_response_required': bool(planned),
               'saved_content': 'aggregates_and_temporary_minimal_labels' if journal else 'deliberately_retained_aggregates_only', 'aggregates_are_anonymous': False,
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
    confirmed = sum(r['status'] == 'ok' for r in journal.data['segments']) if journal else planned if not failed else 0
    unknown = sum(r['status'] == 'unknown' for r in journal.data['segments']) if journal else 0
    complete = failed == 0 and confirmed == planned
    report = {'version': 1, 'mode': 'private-analyze', 'complete': complete,
              'recovery': journal.recovery_stats() if journal else {'policy': 'ram_only_no_recovery'},
              'pause_reason': journal.failure_code if journal and not complete else None,
              'confirmed_classifier_calls': confirmed, 'unknown_classifier_calls': unknown,
              'pending_classifier_calls': planned - confirmed - unknown,
              'analysis_contract': contract, 'planned_classifier_calls': planned,
              'classification_failures': failed, 'selection_coverage': coverage,
              'rubrics': rubric_counts, 'feedback': feedback, 'quality': quality, 'privacy': privacy}
    files = {'report.json': canonical(report) + '\n', 'narrative.json': canonical(story) + '\n',
             'privacy.json': canonical(privacy) + '\n', 'dashboard.html': quality_render(story),
             'feedback.html': feedback_render(feedback, cutoff)}
    from html import escape
    overview = ('<section aria-label="Cobertura da campanha"><h1>' + ('CONCLUÍDA' if complete else 'PARCIAL — não concluída')
                + '</h1><p>Segmentos confirmados: ' + str(confirmed) + '/' + str(planned)
                + '; incertos: ' + str(unknown) + '; pendentes: ' + str(planned - confirmed - unknown)
                + '. Rótulos provisórios não qualificam o modelo.</p><ul>'
                + ''.join('<li>' + escape(name) + ': ' + str(counts['items'] - counts['failed'])
                          + '/' + str(counts['items']) + ' itens confirmados; falhas/não processados: '
                          + str(counts['failed']) + '</li>' for name, counts in rubric_counts.items())
                + '</ul></section>')
    for name in ('dashboard.html', 'feedback.html'):
        # Existing plots and all rubrics remain intact; status is visible above them.
        import re
        files[name] = re.sub(r'(<body\b[^>]*>)', lambda m: m[0] + overview, files[name], count=1)
    if args.resume and output.exists():
        from private_checkpoint import atomic_text
        if any(p.is_symlink() for p in (output, *output.parents)):
            raise ValueError('invalid_work')
        for name, body in files.items():
            atomic_text(output / name, body)
    else:
        _save(output, files)
    if complete and journal is not None:
        from private_checkpoint import sync_directory
        # Barrier is mandatory even when output.mkdir happened in a prior run.
        # Keep decisions until both file data and directory entries are durable.
        for name in files:
            # Windows _commit/FlushFileBuffers requires write access to flush.
            # Exports were just created privately; do not weaken the barrier.
            with (output / name).open('rb+') as stream:
                os.fsync(stream.fileno())
        sync_directory(output)
        sync_directory(output.parent)
        journal.finish({name: hashlib.sha256(body.encode('utf-8')).hexdigest() for name, body in files.items()})
    print(canonical({'mode': 'private-analyze', 'output': str(output), 'planned_classifier_calls': planned,
                     'artifacts': {'dashboard_html': str(output / 'dashboard.html'),
                                   'feedback_html': str(output / 'feedback.html')},
                     'classification_failures': failed, 'complete': complete,
                     'pause_reason': journal.failure_code if journal and not complete else None,
                     'recovery': report['recovery'], 'payload_files_written': False}))
    return 0 if complete else 1


def check(args):
    import cli
    privacy_destination(args.base_url)
    client = cli.configured_client(args)
    model = cli.select_model(client, args.model)
    print(canonical({'privacy_preflight': 'passed', 'model': model, 'scope': 'immediate_api_response_headers_only',
                     'history_read': False, 'classification_sent': False,
                     'not_proof_of_physical_erasure': True}))
    return 0
