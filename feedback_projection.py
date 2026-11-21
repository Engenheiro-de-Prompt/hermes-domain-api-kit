"""Conservative event-copy projection; originals are never modified.

project(root) -> report dictionary, writing only root/unique.
The historical build(root) entry point remains a compatibility alias.
"""
import collections
import hashlib
import json
from pathlib import Path

import feedback_report as report


def project(root, *, timezone_name=report.DEFAULT_TIMEZONE):
    root = Path(root)
    report._check_tree(root)
    report._timezone(timezone_name)
    original = [item for item in json.loads(
        (root / 'corpus.json').read_text(encoding='utf-8'))['items']
        if item.get('kind') == 'feedback']
    groups = collections.defaultdict(list)
    for item in original:
        provenance = item.get('provenance')
        ref = provenance[0] if isinstance(provenance, list) and provenance else {}
        if not isinstance(ref, dict):
            ref = {}
        stamp = ref.get('timestamp')
        sid = ref.get('session_id')
        dated = report._date({'provenance': [ref]}, timezone_name=timezone_name) is not None
        key = (('event', sid, stamp, item['text'])
               if dated and isinstance(sid, str) and sid and isinstance(item.get('text'), str)
               else ('unique', item['id']))
        groups[key].append(item)
    out = root / 'unique'
    out.mkdir(mode=0o700, exist_ok=True)
    merged = []
    keys = {}
    for items in groups.values():
        new_id = hashlib.sha256(json.dumps([i['id'] for i in items], sort_keys=True).encode()).hexdigest()
        # Private staging retains only the timestamp required by the report.
        # IDs are opaque digests; text, paths and session identity never propagate.
        refs = items[0].get('provenance')
        provenance = [{'timestamp': ref.get('timestamp')}
                      for ref in (refs if isinstance(refs, list) else [])
                      if isinstance(ref, dict)]
        merged.append({'id': new_id, 'kind': 'feedback', 'provenance': provenance})
        keys[new_id] = items
    report._write_text(out / 'corpus.json', json.dumps({'items': merged}, ensure_ascii=False))
    disagreements = {}
    for name in report.LABELS:
        src = root / name / 'analysis' / 'results.jsonl'
        rows = report._read_rows(src)
        result = []
        disagreements[name] = 0
        for item in merged:
            originals = keys[item['id']]
            found = [rows.get(x['id']) for x in originals]
            observed = [row for row in found if row is not None]
            failed = any(row.get('status') != 'ok' or row.get('label') not in report.LABELS[name]
                         for row in observed)
            if not failed and len(observed) != len(found):
                continue
            valid = not failed
            labels = {x.get('label') for x in observed} if valid else set()
            if valid and len(labels) > 1:
                disagreements[name] += 1
            result.append({'id': item['id'], 'status': 'ok' if valid else 'error',
                           'label': next(iter(labels)) if valid and len(labels) == 1 else 'indeterminado'})
        path = out / name / 'analysis'
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
        report._write_text(path / 'results.jsonl', ''.join(json.dumps(r) + '\n' for r in result))
    data = report.build(out, timezone_name=timezone_name)
    data['deduplication'] = {
        'policy': 'same session_id + exact timestamp + exact sanitized full text; undated never deduplicated; disagreements abstain; originals preserved',
        'raw_records': len(original), 'unique_events': len(merged),
        'duplicate_copies_removed': len(original) - len(merged),
        'duplicate_label_disagreements': disagreements,
    }
    report._write_text(out / 'report.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return data


build = project


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Project feedback event copies offline.')
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    try:
        data = project(args.root)
    except (OSError, ValueError, KeyError, TypeError):
        parser.exit(1, 'Erro: entrada inválida ou acesso aos arquivos indisponível.\n')
    print(json.dumps(data['deduplication']))
