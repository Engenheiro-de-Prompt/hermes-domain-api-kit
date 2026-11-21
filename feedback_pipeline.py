"""Fluxo portátil explícito. Importar não lê perfil, chave, nem acessa rede."""
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone, timedelta
from html import escape
from pathlib import Path

import analysis
from study import digest

NAMES=('satisfaction','corrections')


def _check_tree(root):
    from feedback_report import _check_tree as check_tree
    check_tree(root)


def _read(path, sealed=False):
    if path.is_symlink() or not path.is_file():raise ValueError('checkpoint_incomplete')
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError):raise ValueError('checkpoint_incomplete') from None
    if not isinstance(data,dict):raise ValueError('invalid_snapshot')
    if sealed:
        seal=data.pop('snapshot_sha256',None)
        if not seal or digest(data)!=seal:raise ValueError('snapshot_integrity_failed')
    return data


def _write_new(path, data, sealed=False):
    if sealed:data={**data,'snapshot_sha256':digest(data)}
    with path.open('x',encoding='utf-8') as stream:
        json.dump(data,stream,ensure_ascii=False,allow_nan=False)
        stream.write('\n')


def _today():
    # O corte atual pós-2019 usa UTC-3; datas históricas ficam no parser do relatório.
    return datetime.now(timezone(timedelta(hours=-3))).date()


def _cutoff(value):
    try:return date.fromisoformat(value) if value else _today()
    except (ValueError,TypeError):raise ValueError('selection_invalid') from None


def render_reports(work, cutoff, timezone_name='America/Sao_Paulo'):
    """Somente disco: não descobre home, configura cliente ou chama modelo."""
    import feedback_report
    import feedback_projection
    from feedback_dashboard import render
    _check_tree(work)
    corpus=_read(work/'corpus.json')
    if 'snapshot_sha256' in corpus:
        corpus=_read(work/'corpus.json',sealed=True)
        if digest(corpus['items'])!=corpus.get('items_sha256'):raise ValueError('snapshot_integrity_failed')
    dates=[feedback_report._date(item,timezone_name=timezone_name) for item in corpus['items'] if item.get('kind')=='feedback']
    dates=[d for d in dates if d is not None]
    if dates and max(dates)>cutoff:raise ValueError('selection_invalid')
    feedback_report.build(work,timezone_name=timezone_name)
    data=feedback_projection.project(work,timezone_name=timezone_name)
    out=work/'unique'
    coverage=corpus.get('coverage',{})
    data['observed_history']={'first_date':str(min(dates)) if dates else None,
        'last_date':str(max(dates)) if dates else None,'installation_date_proven':False,
        'scope':'selected_profile_snapshot_only','source_status':coverage.get('status','unknown'),
        'excluded':coverage.get('excluded',{}),'source_failure_count':len(coverage.get('failures',[]))}
    feedback_report._write_text(out/'report.json',json.dumps(data,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
    page=render(data,cutoff)
    info=data['observed_history']
    exclusions=''.join('<li>'+escape(str(k))+': '+escape(str(v))+'</li>' for k,v in info['excluded'].items())
    metrics=[('Registros brutos',len(corpus['items'])),('Mensagens únicas',data['total_messages']),
        ('Satisfação',data['totals']['satisfaction']['counts']['satisfacao']),
        ('Insatisfação',data['totals']['satisfaction']['counts']['insatisfacao']),
        ('Correção e/ou redirecionamento',data['totals']['corrections']['signal_total'])]
    cards=''.join('<div><dt>'+escape(label)+'</dt><dd>'+escape(str(value) if value is not None else '—')+'</dd></div>' for label,value in metrics)
    scope=f'<section class="scope"><h2>Alcance do histórico disponível</h2><p>Primeiro registro datado: {escape(info["first_date"] or "não disponível")}. Último: {escape(info["last_date"] or "não disponível")}.</p><dl class="metrics">{cards}</dl><p>Isso não comprova a data da primeira instalação nem recupera sessões apagadas, outros perfis ou dados ausentes. A análise usa somente o snapshot selecionado.</p><p>Extração: {escape(str(info["source_status"]))}; falhas de fonte: {info["source_failure_count"]}.</p><details><summary>Exclusões na extração (contagens)</summary><ul>{exclusions}</ul></details></section>'
    layout='<style>main{display:flex;flex-direction:column}main>header{order:0}main>section{order:3}main>section.scope{order:1}main>section.warning{order:2}main>section:has(table){order:4}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.metrics div{padding:12px;background:#f1f5f9;border-radius:8px}.metrics dt{font-size:14px}.metrics dd{margin:0;font-size:28px;font-weight:bold}</style>'
    page=page.replace('</header>','</header>'+scope,1).replace('</head>',layout+'</head>',1)
    feedback_report._write_text(out/'dashboard.html',page)
    partial=coverage.get('status')!='ok' or bool(data.get('missing_timestamps',{}).get('messages')) or any(data['totals'][name]['partial'] for name in NAMES)
    return {'dashboard':str(out/'dashboard.html'),'weekly_csv':str(out/'weekly.csv'),
        'report_json':str(out/'report.json'),'raw_records':len(corpus['items']),
        'unique_events':data['total_messages'],'partial':partial,
        'qualification':'exploratory_not_human_calibrated','observed_history':info}


def execute(args):
    import cli
    if not args.work:raise ValueError('explicit_work_required')
    if args.limit is not None or args.sources or args.rubric!='domain':raise ValueError('selection_invalid')
    if not 0<=args.context_chars<=1200:raise ValueError('selection_invalid')
    if args.command=='feedback-report' and (args.home or args.session or args.delegation!='human' or args.context_chars!=1200):
        raise ValueError('selection_options_only_at_extraction')
    cutoff=_cutoff(args.cutoff)
    import feedback_report
    from zoneinfo import ZoneInfoNotFoundError
    try:tz=feedback_report._timezone(args.timezone)
    except (ZoneInfoNotFoundError,ValueError):raise ValueError('timezone_data_missing') from None
    if not args.cutoff:cutoff=datetime.now(tz).date()
    work=cli.private_work(args.work)
    _check_tree(work)
    print(json.dumps({'event':'campaign','work':str(work),'notice':'Dados privados; guarde esta pasta para retomar.'},ensure_ascii=False),file=sys.stderr,flush=True)
    lock_path=work/'pipeline.lock.sqlite'
    if lock_path.is_symlink():raise ValueError('invalid_snapshot')
    lock=sqlite3.connect(lock_path,timeout=0)
    try:
        try:lock.execute('BEGIN IMMEDIATE')
        except sqlite3.OperationalError as exc:
            if 'locked' in str(exc).lower():raise ValueError('pipeline_busy') from None
            raise
        manifest_path=work/'pipeline.json';snapshot=work/'corpus.json'
        if args.command=='feedback-report':
            if not args.cutoff and manifest_path.exists():cutoff=_cutoff(_read(manifest_path,sealed=True)['cutoff'])
            result=render_reports(work,cutoff,args.timezone)
            print(json.dumps(result,ensure_ascii=False))
            return 1 if result['partial'] else 0
        from extractor import discover_home
        from selection import extract_selected
        home=discover_home(args.home).resolve()
        rubrics={name:analysis.load_rubric(Path(__file__).parent/'rubrics'/f'{name}.json') for name in NAMES}
        identity={'version':1,'home_sha256':digest(str(home)),'timezone':args.timezone,
            'base_sha256':digest(args.base_url.rstrip('/')),
            'selection':{'sessions':sorted(set(args.session)),'delegation':args.delegation,'context_chars':args.context_chars},
            'rubrics_sha256':digest(rubrics)}
        exists=(manifest_path.exists(),snapshot.exists())
        if any(exists) and not all(exists):raise ValueError('checkpoint_incomplete')
        if all(exists):
            saved=_read(manifest_path,sealed=True)
            if any(saved.get(k)!=v for k,v in identity.items()) or (args.model and args.model!=saved['model']) or (args.cutoff and str(cutoff)!=saved['cutoff']):
                raise ValueError('campaign_mismatch')
            corpus=_read(snapshot,sealed=True)
            if digest(corpus['items'])!=corpus.get('items_sha256') or digest(corpus)!=saved['corpus_sha256']:
                raise ValueError('snapshot_integrity_failed')
            model=saved['model'];cutoff=_cutoff(saved['cutoff'])
            client=cli.configured_client(args)
        else:
            if any((work/name).exists() for name in NAMES):raise ValueError('checkpoint_incomplete')
            client=cli.configured_client(args)
            model=cli.select_model(client,args.model)
            corpus=extract_selected(home,sources=['feedback'],session_ids=args.session,delegation=args.delegation,context_chars=args.context_chars)
            if not isinstance(corpus,dict):raise ValueError('invalid_snapshot')
            if corpus.get('coverage',{}).get('status')!='ok':raise ValueError('incomplete_corpus')
            if not corpus['items']:raise ValueError('empty_corpus')
            corpus['source_home_sha256']=identity['home_sha256']
            corpus['items_sha256']=digest(corpus['items'])
            _write_new(snapshot,corpus,sealed=True)
            _write_new(manifest_path,{**identity,'model':model,'cutoff':str(cutoff),'corpus_sha256':digest(corpus)},sealed=True)
        if corpus.get('coverage',{}).get('status')!='ok':raise ValueError('incomplete_corpus')
        summaries={name:analysis.classify(corpus['items'],client,model,work/name/'analysis',rubric=rubrics[name],progress=cli.progress_report) for name in NAMES}
        result=render_reports(work,cutoff,args.timezone)
        result['analyses']=summaries
        print(json.dumps(result,ensure_ascii=False))
        return 1 if result['partial'] or any(s['failed'] for s in summaries.values()) else 0
    finally:lock.close()
