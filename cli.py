"""CLI de consumo; configuração privada fora do repositório."""
import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_API_BASE_URL='https://homegrown-ai-bridge.lovable.app/api/public/v1'
ERROR_HINTS={
    'invalid_key':'Use uma chave CLIENT, não AGENT, OpenAI ou backend; forneça por arquivo privado ou prompt local sem eco.',
    'key_not_provisioned':'Informe --key-file com um arquivo privado de chave CLIENT ou execute em terminal interativo seguro.',
    'invalid_key_file':'Use um arquivo regular privado contendo somente a chave CLIENT, sem Bearer ou aspas.',
    'insecure_key_file_permissions':'No Linux/macOS, restrinja o arquivo da chave com chmod 600; no Windows, configure as ACLs.',
    'relay_consent_required':'O texto será enviado ao relay. Se esse escopo já foi autorizado, execute com --allow-relay.',
    'http_401':'O servidor recusou a chave CLIENT. Verifique validade, papel e uma variável de ambiente antiga.',
    'http_403':'A chave não tem autorização para esta operação; consulte o operador da API.',
    'http_504':'O relay não entregou resultado no prazo. O operador deve verificar conector e backend no PC dos modelos.',
    'timeout':'A resposta não chegou no prazo. Preserve a campanha; não apague o checkpoint para repetir pedidos.',
    'campaign_mismatch':'Para retomar, preserve URL, modelo, corpus e opções. Para alterá-los, crie outra pasta --work.',
    'incomplete_corpus':'Revise a cobertura no corpus privado e corrija a fonte antes de criar nova campanha.',
    'source_home_mismatch':'O snapshot pertence a outro perfil ou não tem identidade verificável. Use o home original ou crie outra pasta --work.',
}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse diagnostics can contain arbitrary private argument values.
        self.exit(2, json.dumps({'error':'invalid_arguments'})+'\n')


def parser():
    p=SafeArgumentParser(description='Classifique seu Hermes sem modelos neste PC. Use chave CLIENT, não AGENT.',epilog='Fluxo completo autorizado: python3 cli.py classify-all --allow-relay --work ../minha-classificacao. Guia: README.md e docs/USAGE.md.')
    p.add_argument('command',choices=['classify-all','models','verify','extract','run','rubrics','extract-selected','analyze','verify-analysis'],help='Legado: classify-all/models/verify/extract/run. Modular: rubrics/extract-selected/analyze/verify-analysis')
    p.add_argument('--base-url',default=os.environ.get('HERMES_CLASSIFIER_API_BASE') or DEFAULT_API_BASE_URL)
    p.add_argument('--key-file',default=os.environ.get('HERMES_CLASSIFIER_KEY_FILE'))
    p.add_argument('--home',help='HERMES_HOME selecionado; não explora outros perfis')
    p.add_argument('--work',help='Pasta privada para checkpoint e resultados; classify-all cria uma pasta exclusiva se omitida')
    p.add_argument('--model',help='ID literal do catálogo; classificação CLEF, sem fallback para chat')
    p.add_argument('--allow-relay',action='store_true',help='Autoriza enviar o snapshot sanitizado ao relay hospedado')
    p.add_argument('--limit',type=int,help='Primeiros N itens do snapshot; congelado por campanha')
    p.add_argument('--rubric', default='domain', help='domain, feedback ou arquivo JSON de rubrica')
    p.add_argument('--sources', nargs='+', choices=['tasks','feedback','skills','memories'], help='Fontes explícitas para extract-selected; padrão acompanha a rubrica')
    p.add_argument('--session', action='append', default=[], help='ID exato de sessão; repetível; só afeta mensagens')
    p.add_argument('--delegation', choices=['all','human','subagent'], default='human', help='Seleção modular: human exclui subagentes por padrão')
    p.add_argument('--context-chars', type=int, default=1200, help='Contexto auxiliar de feedback, 0 a 1200 caracteres')
    p.add_argument('--timeout',type=float,default=145)
    return p


def default_work():
    return Path.home()/'.local/share/hermes-domain-api-kit/default'


def progress_report(progress):
    print(json.dumps({'progress':progress},ensure_ascii=False),file=sys.stderr,flush=True)


def private_work(value):
    work=Path(value).expanduser().resolve()
    repo=Path(__file__).resolve().parent
    if work==repo or repo in work.parents:raise ValueError('work_must_be_outside_repository')
    if work.exists() and work.is_symlink():raise ValueError('invalid_work')
    work.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(work,0o700)
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
        if path.is_symlink() or not path.is_file() or path.stat().st_size>4096:raise ValueError('invalid_key_file')
        if os.name=='posix' and path.stat().st_mode & 0o077:raise ValueError('insecure_key_file_permissions')
        key=path.read_text(encoding='utf-8').strip()
    if not key:
        if not sys.stdin.isatty():raise ValueError('key_not_provisioned')
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
    old_umask=os.umask(0o077)
    if args.command in ('run','classify-all','analyze','verify-analysis') and not args.allow_relay:
        print(json.dumps({'error':'relay_consent_required','hint':ERROR_HINTS['relay_consent_required']},ensure_ascii=False),file=sys.stderr)
        os.umask(old_umask)
        return 2
    try:
        if args.command in ('rubrics','extract-selected','analyze','verify-analysis'):
            from modular_cli import execute
            return execute(args)
        if args.sources or args.session or args.rubric != 'domain' or args.delegation != 'human' or args.context_chars != 1200:
            raise ValueError('modular_options_require_modular_command')
        if args.command=='classify-all':
            from datetime import datetime,timezone
            from extractor import discover_home, extract
            from study import save_json, digest, classify_records

            if args.limit is not None:raise ValueError('invalid_limit')
            client=configured_client(args)
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            work=private_work(args.work or (Path.home()/'.local/share/hermes-domain-api-kit/runs'/stamp))
            print(json.dumps({'event':'campaign','work':str(work),'notice':'Guarde esta pasta para retomar com --work; não compartilhe os dados.'},ensure_ascii=False),file=sys.stderr,flush=True)
            selected_home=discover_home(args.home)
            home_identity=digest(str(selected_home.resolve()))
            snapshot=work/'corpus.json'
            if snapshot.is_symlink():raise ValueError('invalid_snapshot')
            if snapshot.exists():
                corpus=json.loads(snapshot.read_text(encoding='utf-8'))
                if corpus.get('source_home_sha256')!=home_identity:raise ValueError('source_home_mismatch')
                if digest(corpus['items'])!=corpus['items_sha256']:raise ValueError('snapshot_integrity_failed')
            else:
                corpus=extract(selected_home)
                if not isinstance(corpus,dict):raise ValueError('incomplete_corpus')
                corpus['source_home_sha256']=home_identity
                corpus['items_sha256']=digest(corpus['items'])
                save_json(snapshot,corpus)
            if corpus.get('coverage',{}).get('status')!='ok':raise ValueError('incomplete_corpus')
            if not corpus['items']:raise ValueError('empty_corpus')
            model=select_model(client,args.model)
            bundle=work/'classification_bundle.zip'
            summary=classify_records(corpus['items'],client,model,work/'classification',progress=progress_report,bundle_path=bundle)
            report={'items':len(corpus['items']),'coverage_status':corpus['coverage']['status'],
                    'sources_count':len(corpus['coverage']['sources_read']),'excluded':corpus['coverage']['excluded'],
                    'model':model,'summary':summary,'bundle':str(bundle)}
            print(json.dumps(report,ensure_ascii=False))
            return 0 if summary['failed']==0 else 1
        if args.command=='extract':
            from extractor import discover_home, extract
            from study import save_json, digest
            work=private_work(args.work or default_work()); path=work/'corpus.json'
            if path.exists():raise ValueError('snapshot_already_exists_use_new_work')
            corpus=extract(discover_home(args.home))
            corpus['items_sha256']=digest(corpus['items'])
            save_json(path,corpus)
            print(json.dumps({'items':len(corpus['items']),'coverage':corpus['coverage']},ensure_ascii=False))
            return 0 if corpus['coverage'].get('status')=='ok' else 1
        from study import digest, classify_records
        if args.command=='run':
            if args.limit is not None and args.limit<1:raise ValueError('invalid_limit')
            work=private_work(args.work or default_work())
            corpus=json.loads((work/'corpus.json').read_text(encoding='utf-8'))
            if corpus.get('coverage',{}).get('status','ok')!='ok':raise ValueError('incomplete_corpus')
            if digest(corpus['items'])!=corpus['items_sha256']:raise ValueError('snapshot_integrity_failed')
            items=corpus['items'] if args.limit is None else corpus['items'][:args.limit]
            if not items:raise ValueError('empty_corpus')
            client=configured_client(args);model=select_model(client,args.model)
            result=classify_records(items,client,model,work/'classification',progress=progress_report)
            print(json.dumps(result,ensure_ascii=False))
            return 0 if result['failed']==0 else 1
        if args.command=='verify':
            from synthetic import CASES, items as synthetic_items
            from study import save_json, LABELS
            work=private_work(args.work or default_work())
            client=configured_client(args);model=select_model(client,args.model)
            records=synthetic_items()
            summary=classify_records(records,client,model,work/'verification',progress=progress_report)
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
        allowed={'snapshot_already_exists_use_new_work','work_must_be_outside_repository','checkpoint_incomplete','campaign_mismatch','incomplete_corpus','invalid_limit','empty_corpus','snapshot_integrity_failed','invalid_catalog','classifier_not_advertised','choose_clef_model_from_catalog','key_not_provisioned','invalid_key_file','insecure_key_file_permissions','incomplete_result_artifacts','invalid_result_directory','invalid_result_artifacts','source_home_mismatch','explicit_work_required','selection_options_only_at_extraction','rubric_source_mismatch','selection_invalid','invalid_rubric','invalid_snapshot','unsupported_verification_rubric','modular_options_require_modular_command'}
        code=str(error) if isinstance(error,ValueError) and str(error) in allowed else type(error).__name__
        from api_client import ClientError
        if isinstance(error,ClientError):code=error.code
        print(json.dumps({'error':code,'hint':ERROR_HINTS.get(code,'Consulte docs/USAGE.md: diagnóstico. Não compartilhe chaves, textos privados ou logs brutos.')},ensure_ascii=False),file=sys.stderr)
        return 2
    finally:
        os.umask(old_umask)

if __name__=='__main__':raise SystemExit(main())
