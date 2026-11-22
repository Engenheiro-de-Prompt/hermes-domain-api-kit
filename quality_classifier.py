"""Private, provisional event classification; never upgrades source evidence."""
import json
from pathlib import Path

import analysis
from study import digest

CLASSIFIER_VERSION = 'quality-classifier-v1'
SCHEMA_VERSION = 1
_PROVENANCE_KEYS = ('tenant_id', 'source_id', 'session_id', 'event_id', 'task_id',
                    'event_type', 'timestamp', 'actor')


def _project(row, event, rubric, label_name, model):
    failed = row['status'] != 'ok' or any(chunk['status'] != 'ok' for chunk in row['chunks'])
    label = rubric['unknown'] if failed else row['label']
    score = None
    reason = None
    if failed:
        reason = 'classification_failed'
    elif len(row['chunks']) != 1:
        reason = ('conflicting_chunk_labels' if len({chunk['label'] for chunk in row['chunks']}) > 1
                  else 'multiple_chunks_no_single_label_score')
    else:
        score = row['chunks'][0]['scores'][label]
        if label == rubric['unknown']:
            reason = 'model_abstention'
    return {
        'source_id': event['source_id'], 'event_id': event['event_id'],
        'task_id': event['task_id'], 'label_name': label_name,
        'label_value': label, 'classifier_score_raw': score,
        'score_type': 'model_class_distribution_uncalibrated',
        'evidence_event_ids': [event['event_id']],
        'evidence_scope': 'input_event_reference_only',
        'origin': 'classifier_inference', 'is_observable': False,
        'review_required': True, 'unknown_reason': reason,
        'model_id': model, 'prompt_version': rubric['version'],
        'classifier_version': CLASSIFIER_VERSION, 'schema_version': SCHEMA_VERSION}


def classify_events(events, client, model, output, *, checkpoint_manifest=None):
    """Return inference labels without changing input events.

    Caller supplies authorized, normalized events. No history is read or linked;
    context is empty and each provenance entry refers only to its own event.
    Checkpoints and raw text remain private under quality_correction/quality_outcome.
    Failed/interrupted attempts are terminal, including on resume. No retry here.
    evidence_event_ids references input only, never independent corroboration.
    """
    events = list(events)
    labels = []
    plans = []
    for rubric_name, label_name, kind in (
            ('quality_correction', 'explicit_user_correction', 'feedback'),
            ('quality_outcome', 'outcome', 'task')):
        items = []
        originals = {}
        for event in events:
            text = event.get('text')
            eligible = (event.get('actor') == 'user' if kind == 'feedback' else
                        event.get('actor') == 'assistant' or event.get('event_type') == 'delivery')
            if not eligible or not isinstance(text, str) or not text.strip():
                continue
            item_id = digest([event['tenant_id'], event['source_id'], event['event_id']])
            originals[item_id] = event
            items.append({'id': item_id, 'kind': kind, 'text': text,
                          'context': '', 'context_missing': True, 'context_truncated': False,
                          'provenance': [{key: event.get(key) for key in _PROVENANCE_KEYS}]})
        if not items:
            continue
        rubric = analysis.load_rubric(Path(__file__).parent / 'rubrics' / (rubric_name + '.json'))
        plans.append((rubric, label_name, items, originals))
    if not plans:
        return []
    output = Path(output)
    if any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('invalid_output')
    mp = Path(checkpoint_manifest) if checkpoint_manifest is not None else output / 'checkpoints.json'
    if any(p.is_symlink() for p in (mp, *mp.parents)):
        raise ValueError('invalid_output')
    contract = digest([events, model, client.base_url])
    if mp.is_symlink():
        raise ValueError('invalid_output')
    if mp.exists():
        try:
            state = json.loads(mp.read_text(encoding='utf-8'))
            if (not isinstance(state, dict) or set(state) != {'version', 'contract', 'started'}
                    or type(state['version']) is not int or state['version'] != 1
                    or not isinstance(state['started'], list)
                    or any(type(name) is not str or name not in {'quality_correction', 'quality_outcome'}
                           for name in state['started'])
                    or len(set(state['started'])) != len(state['started'])):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError('checkpoint_incomplete') from None
        if state['contract'] != contract:
            raise ValueError('campaign_mismatch')
        # Validar TODAS as rubricas iniciadas antes de qualquer inferência.
        for name in state['started']:
            directory = output / name
            required = [directory / 'manifest.json', directory / 'decisions.sqlite']
            if (directory.is_symlink() or any(p.is_symlink() or not p.is_file()
                    or p.stat().st_size == 0 for p in required)):
                raise ValueError('checkpoint_incomplete')
    else:
        if output.exists() and any(output.iterdir()):
            raise ValueError('checkpoint_incomplete')
        output.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = {'version': 1, 'contract': contract, 'started': []}
        analysis._write(mp, json.dumps(state, sort_keys=True) + '\n')
    for rubric, label_name, items, originals in plans:
        directory = output / rubric['id']
        if rubric['id'] not in state['started']:
            # Gravar antes da primeira tentativa: interrupção não autoriza replay.
            state['started'].append(rubric['id'])
            analysis._write(mp, json.dumps(state, sort_keys=True) + '\n')
        analysis.classify(items, client, model, directory, rubric=rubric)
        with (directory / 'results.jsonl').open(encoding='utf-8') as stream:
            for line in stream:
                row = json.loads(line)
                labels.append(_project(row, originals[row['id']], rubric, label_name, model))
    return labels
