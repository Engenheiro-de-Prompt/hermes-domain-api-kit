"""Pure ephemeral feedback aggregation; inputs and decisions never leave memory."""
from datetime import timedelta

from feedback_report import LABELS, _date, _summary, _timezone


def _rows(records):
    """Repeated identical results are harmless; conflicting results fail closed."""
    rows = {}
    for record in records:
        ident = record['id']
        row = {'status': record.get('status'), 'label': record.get('label')}
        previous = rows.get(ident)
        if previous is not None and previous != row:
            row = {'status': 'error', 'label': None}
        rows[ident] = row
    return rows


def build(items, labels, *, timezone_name='UTC'):
    """Return the report schema using only in-memory inputs.

    Weekly rates include every dated feedback message. As in feedback_report,
    totals include undated messages; missing_timestamps also describes them
    separately. The parent owns source completeness via observed_history.
    """
    _timezone(timezone_name)
    selected = [item for item in items if item.get('kind') == 'feedback']
    raw_count = len(selected)
    groups = {}
    for index, item in enumerate(selected):
        refs = item.get('provenance')
        ref = refs[0] if isinstance(refs, list) and refs else {}
        ref = ref if isinstance(ref, dict) else {}
        sid, stamp = ref.get('session_id'), ref.get('timestamp')
        dated = _date({'provenance': [ref]}, timezone_name=timezone_name) is not None
        key = (('event', sid, type(stamp), stamp, item['text'])
               if dated and isinstance(sid, str) and sid and isinstance(item.get('text'), str)
               else ('unique', index))
        groups.setdefault(key, []).append(item)
    source_rows = {name: _rows(labels.get(name, [])) for name in LABELS}
    disagreements = dict.fromkeys(LABELS, 0)
    selected, rows = [], {name: {} for name in LABELS}
    for index, copies in enumerate(groups.values()):
        refs = copies[0].get('provenance')
        provenance = [{'timestamp': ref.get('timestamp')}
                      for ref in (refs if isinstance(refs, list) else [])
                      if isinstance(ref, dict)]
        selected.append({'id': index, 'provenance': provenance})
        for name in LABELS:
            found = [source_rows[name].get(item['id']) for item in copies]
            observed = [row for row in found if row is not None]
            failed = any(row.get('status') != 'ok' or row.get('label') not in LABELS[name]
                         for row in observed)
            if failed:
                rows[name][index] = {'status': 'error'}
            elif len(observed) == len(found):
                decisions = {row['label'] for row in observed}
                if len(decisions) > 1:
                    disagreements[name] += 1
                rows[name][index] = {'status': 'ok', 'label':
                    next(iter(decisions)) if len(decisions) == 1 else 'indeterminado'}
    buckets = {}
    missing = []
    for item in selected:
        day = _date(item, timezone_name=timezone_name)
        if day is None:
            missing.append(item)
        else:
            monday = day - timedelta(days=day.weekday())
            buckets.setdefault(monday, []).append(item)
    weeks = []
    if buckets:
        monday = min(buckets)
        while monday <= max(buckets):
            group = buckets.get(monday, [])
            weeks.append({'week': monday.isoformat(), 'messages': len(group),
                          **{name: _summary(group, rows[name], name) for name in LABELS}})
            monday += timedelta(days=7)
    return {'timezone': timezone_name, 'weeks': weeks,
            'deduplication': {
                'policy': 'same session_id + exact timestamp + exact full text; undated never deduplicated; disagreements abstain; originals preserved',
                'raw_records': raw_count, 'unique_events': len(selected),
                'duplicate_copies_removed': raw_count - len(selected),
                'duplicate_label_disagreements': disagreements},
            'dated_messages': len(selected) - len(missing),
            'total_messages': len(selected),
            'totals': {name: _summary(selected, rows[name], name) for name in LABELS},
            'missing_timestamps': {'messages': len(missing),
                **{name: _summary(missing, rows[name], name) for name in LABELS}}}
