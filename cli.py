"""CLI de consumo; configuração privada fora do repositório."""
import argparse
import json
import os
import sys
from pathlib import Path


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse diagnostics can contain arbitrary private argument values.
        self.exit(2, json.dumps({'error':'invalid_arguments'})+'\n')


def parser():
    p=SafeArgumentParser(description='Hermes → extração privada → CLEF por API. Sem modelos no cliente.')
    p.add_argument('command',choices=['models','verify','extract','run'])
    p.add_argument('--base-url',default=os.environ.get('HERMES_CLASSIFIER_API_BASE'))
    p.add_argument('--key-file',default=os.environ.get('HERMES_CLASSIFIER_KEY_FILE'))
    p.add_argument('--home',help='HERMES_HOME selecionado; não explora outros perfis')
    p.add_argument('--work',default=str(Path.home()/'.local/share/hermes-domain-api-kit/default'))
    p.add_argument('--model',help='ID literal do catálogo; classificação CLEF, sem fallback para chat')
    p.add_argument('--allow-relay',action='store_true',help='Autoriza enviar o snapshot sanitizado ao relay hospedado')
    p.add_argument('--limit',type=int,help='Primeiros N itens do snapshot; congelado por campanha')
    p.add_argument('--timeout',type=float,default=145)
    return p


def private_work(value):
    work=Path(value).expanduser().resolve()
    repo=Path(__file__).resolve().parent
    if work==repo or repo in work.parents:raise ValueError('work_must_be_outside_repository')
    if work.exists() and work.is_symlink():raise ValueError('invalid_work')
    work.mkdir(parents=True,exist_ok=True,mode=0o700)
    return work


def configured_client(args):
    import getpass
    import warnings
    from api_client import RelayClient
    # Validate destination and timeout BEFORE reading any secret file.
    RelayClient(args.base_url,'validation-only-synthetic',timeout=args.timeout)
    key=os.environ.get('HERMES_CLASSIFIER_API_KEY')
    if not key and args.key_file:
        path=Path(args.key_file).expanduser()
        if path.is_symlink() or path.stat().st_size>4096:raise ValueError('invalid_key_file')
        key=path.read_text(encoding='utf-8').strip()
    if not key:
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            key=getpass.getpass('Chave CLIENT (sem eco): ').strip()
    client=RelayClient(args.base_url,key,timeout=args.timeout)
    client.base_url=args.base_url.rstrip('/')
    return client


def select_model(client, requested):
    data=client.models().get('data')
    if not isinstance(data,list):raise ValueError('invalid_catalog')
    found=[x.get('id') for x in data if isinstance(x,dict) and x.get('task')=='classification' and isinstance(x.get('id'),str)]
    if requested:
        if requested not in found:raise ValueError('classifier_not_advertised')
        return requested
    if 'clef-flash-9b-q4-k-m' in found:return 'clef-flash-9b-q4-k-m'
    clef=[x for x in found if 'clef' in x.lower()]
    if len(clef)==1:return clef[0]
    raise ValueError('choose_clef_model_from_catalog')


def main(argv=None):
    args=parser().parse_args(argv)
    os.umask(0o077)
    if args.command=='run' and not args.allow_relay:
        print(json.dumps({'error':'relay_consent_required'}),file=sys.stderr)
        return 2
    try:
        if args.command=='extract':
            from extractor import discover_home, extract
            from study import save_json, digest
            work=private_work(args.work); path=work/'corpus.json'
            if path.exists():raise ValueError('snapshot_already_exists_use_new_work')
            corpus=extract(discover_home(args.home))
            corpus['items_sha256']=digest(corpus['items'])
            save_json(path,corpus)
            print(json.dumps({'items':len(corpus['items']),'coverage':corpus['coverage']},ensure_ascii=False))
            return 0 if corpus['coverage'].get('status')=='ok' else 1
        from study import digest, classify_records
        if args.command=='run':
            if args.limit is not None and args.limit<1:raise ValueError('invalid_limit')
            work=private_work(args.work)
            corpus=json.loads((work/'corpus.json').read_text(encoding='utf-8'))
            if corpus.get('coverage',{}).get('status','ok')!='ok':raise ValueError('incomplete_corpus')
            if digest(corpus['items'])!=corpus['items_sha256']:raise ValueError('snapshot_integrity_failed')
            items=corpus['items'] if args.limit is None else corpus['items'][:args.limit]
            if not items:raise ValueError('empty_corpus')
            client=configured_client(args);model=select_model(client,args.model)
            result=classify_records(items,client,model,work/'classification')
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result['failed']==0 else 1
        if args.command=='verify':
            from synthetic import CASES, items as synthetic_items
            from study import save_json, LABELS
            work=private_work(args.work)
            client=configured_client(args);model=select_model(client,args.model)
            records=synthetic_items()
            summary=classify_records(records,client,model,work/'verification')
            predictions={}
            for label in LABELS:
                for line in (work/'verification/datasets'/ (label+'.jsonl')).read_text(encoding='utf-8').splitlines():
                    row=json.loads(line);predictions[row['id']]=row
            checks=[{'id':item['id'],'expected':case[0],'observed':predictions[item['id']]['label'],'status':predictions[item['id']]['status'],
                     'matched':predictions[item['id']]['status']=='ok' and predictions[item['id']]['label']==case[0]} for item,case in zip(records,CASES)]
            result={'total':len(checks),'matched':sum(x['matched'] for x in checks),'all_expected_labels_matched':all(x['matched'] for x in checks),
                    'transport_complete':summary['failed']==0,'model':model,'checks':checks,'qualification':'not_established_smoke_only'}
            save_json(work/'verification/result.json',result)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result['all_expected_labels_matched'] else 1
        if args.command=='models':
            client=configured_client(args)
            data=client.models()
            rows=[{'id':r['id'],'task':r.get('task')} for r in data['data'] if isinstance(r,dict) and isinstance(r.get('id'),str)]
            print(json.dumps({'data':rows},ensure_ascii=False))
            return 0
        raise ValueError('command_not_implemented')
    except Exception as error:
        # Never echo paths, URL inputs, keys, private texts or remote error bodies.
        allowed={'snapshot_already_exists_use_new_work','work_must_be_outside_repository','campaign_mismatch','incomplete_corpus','invalid_limit','empty_corpus','snapshot_integrity_failed','invalid_catalog','classifier_not_advertised','choose_clef_model_from_catalog'}
        code=str(error) if isinstance(error,ValueError) and str(error) in allowed else type(error).__name__
        from api_client import ClientError
        if isinstance(error,ClientError):code=error.code
        print(json.dumps({'error':code}),file=sys.stderr)
        return 2

if __name__=='__main__':raise SystemExit(main())
