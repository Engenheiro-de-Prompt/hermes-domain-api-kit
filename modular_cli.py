"""Explicit modular workflows. Importing this module never reads a Hermes home."""
import json
import sys
from pathlib import Path

from analysis import classify, load_rubric
from study import digest, save_json


SOURCE_KIND = {'tasks': 'task', 'feedback': 'feedback', 'skills': 'skill', 'memories': 'memory'}


def execute(args):
    import cli
    if args.command == 'rubrics':
        print(json.dumps({'rubrics': [load_rubric(name) for name in ('domain', 'feedback')]}, ensure_ascii=False))
        return 0
    rubric = load_rubric(args.rubric)
    if not args.work:
        raise ValueError('explicit_work_required')
    if args.command != 'extract-selected' and (args.sources or args.session or args.home or args.delegation != 'human' or args.context_chars != 1200):
        raise ValueError('selection_options_only_at_extraction')
    if args.limit is not None and (args.command != 'analyze' or args.limit < 1):
        raise ValueError('invalid_limit')
    work = cli.private_work(args.work)
    print(json.dumps({'event': 'campaign', 'work': str(work), 'notice': 'Dados privados; preserve esta pasta para retomar.'}, ensure_ascii=False), file=sys.stderr, flush=True)
    if args.command == 'extract-selected':
        from extractor import discover_home
        from selection import extract_selected
        if not 0 <= args.context_chars <= 1200:
            raise ValueError('selection_invalid')
        sources = args.sources if args.sources is not None else [s for s, kind in SOURCE_KIND.items() if kind in rubric['kinds']]
        if not sources or any(SOURCE_KIND[s] not in rubric['kinds'] for s in sources):
            raise ValueError('rubric_source_mismatch')
        snapshot = work / 'corpus.json'
        # Exclusive creation prevents overwriting a frozen snapshot under concurrency.
        if snapshot.exists() or snapshot.is_symlink():
            raise ValueError('snapshot_already_exists_use_new_work')
        corpus = extract_selected(discover_home(args.home).resolve(), sources=sources,
                                  session_ids=args.session, delegation=args.delegation,
                                  context_chars=args.context_chars)
        corpus['source_home_sha256'] = digest(str(discover_home(args.home).resolve()))
        corpus['items_sha256'] = digest(corpus['items'])
        corpus['snapshot_sha256'] = digest(corpus)
        with snapshot.open('x', encoding='utf-8') as stream:
            json.dump(corpus, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
        print(json.dumps({'items': len(corpus['items']), 'coverage_status': corpus['coverage']['status'],
                          'source_counts': corpus['coverage']['source_counts'], 'scope': 'selection'}, ensure_ascii=False))
        return 0 if corpus['coverage']['status'] == 'ok' else 1
    if args.command == 'analyze':
        path = work / 'corpus.json'
        if path.is_symlink():
            raise ValueError('invalid_snapshot')
        corpus = json.loads(path.read_text(encoding='utf-8'))
        seal = corpus.pop('snapshot_sha256', None)
        if not seal or digest(corpus) != seal or digest(corpus['items']) != corpus.get('items_sha256'):
            raise ValueError('snapshot_integrity_failed')
        if corpus.get('coverage', {}).get('status') != 'ok':
            raise ValueError('incomplete_corpus')
        items = corpus['items'] if args.limit is None else corpus['items'][:args.limit]
        if not items:
            raise ValueError('empty_corpus')
        if any(item['kind'] not in rubric['kinds'] for item in items):
            raise ValueError('rubric_source_mismatch')
        client = cli.configured_client(args)
        model = cli.select_model(client, args.model)
        result = classify(items, client, model, work / 'analysis', rubric=rubric, progress=cli.progress_report)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['failed'] == 0 else 1
    if args.command == 'verify-analysis':
        from modular_synthetic import cases
        examples = cases(rubric['id'])
        records = [record for record, expected in examples]
        client = cli.configured_client(args)
        model = cli.select_model(client, args.model)
        output = work / 'verification'
        summary = classify(records, client, model, output, rubric=rubric, progress=cli.progress_report)
        rows = {row['id']: row for row in (json.loads(line) for line in (output / 'results.jsonl').read_text(encoding='utf-8').splitlines())}
        checks = [{'id': record['id'], 'expected': expected, 'observed': rows[record['id']]['label'],
                   'matched': rows[record['id']]['status'] == 'ok' and rows[record['id']]['label'] == expected}
                  for record, expected in examples]
        result = {'total': len(checks), 'matched': sum(c['matched'] for c in checks),
                  'all_expected_labels_matched': all(c['matched'] for c in checks), 'transport_complete': summary['failed'] == 0,
                  'model': model, 'rubric': rubric['id'], 'qualification': 'not_established_smoke_only', 'checks': checks}
        save_json(output / 'result.json', result)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['all_expected_labels_matched'] else 1
    raise ValueError('command_not_implemented')
