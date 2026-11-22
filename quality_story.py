"""Narrativa agregada determinística; não lê arquivos nem chama modelos.

Recebe apenas o relatório e, opcionalmente, a projeção por tarefa já validada.
A saída é uma allowlist de agregados para apresentação, nunca texto de eventos.
"""
VERSION = 'executive-quality-v1'


def percent(value):
    """Formata uma taxa como percentual PT-BR, preservando ausência de medida."""
    return 'Não mensurável' if value is None else format(100 * value, '.1f').replace('.', ',') + '%'


def ratio(metric):
    return f"{metric['numerator']} / {metric['denominator']}"


def _card(key, title, metric, note):
    coverage = metric.get('coverage', {})
    base = ratio(metric)
    if coverage:
        base += f" · elegíveis {coverage['known']} / {coverage['total']}"
    return dict(key=key, title=title, display=percent(metric['value']), base=base,
                note=note, tone='neutral' if metric['value'] is None else 'info')


def _row(label, value, denominator=None, note=''):
    return dict(label=label, value=value, display='Não mensurável' if value is None else str(value),
                denominator=denominator, note=note)


def _chart(key, title, description, rows, unit='grupos'):
    return dict(key=key, title=title, description=description, unit=unit, rows=rows,
                empty_reason='Sem base observada.' if not rows or not any(r['value'] for r in rows) else None)


def duration(value):
    """Exibe duração observada em unidade legível, sem completar dados ausentes."""
    if value is None:
        return 'Não mensurável'
    divisor, suffix = (3600, 'h') if value >= 3600 else ((60, 'min') if value >= 60 else (1, 's'))
    return format(value / divisor, '.3g').replace('.', ',') + ' ' + suffix


def _insight(key, title, body, action, tone='info'):
    return dict(key=key, title=title, body=body, action=action, tone=tone)


def _executive(story, metrics, n):
    first, correction = metrics['first_attempt_resolution'], metrics['tasks_with_correction']
    unknown, cost = metrics['unknown_resolution'], metrics['cost_per_resolved_task']
    first_band = ('unknown' if first['value'] is None else 'all_eligible' if first['value'] == 1
                  else 'at_least_half' if first['value'] >= .5 else 'below_half')
    correction_band = ('unknown' if correction['value'] is None else 'none_observed' if correction['value'] == 0
                       else 'at_least_30_percent' if correction['value'] >= .3 else 'some_observed')
    coverage = 'none' if not first['denominator'] else 'complete' if first['denominator'] == n else 'partial'
    story['bands'] = dict(first=first_band, correction=correction_band, eligibility=coverage)
    story['kpis'].insert(2, _card('correction', 'Tarefas com correção humana', correction,
                                'Correção tipada; aprovação e esclarecimento não contam como erro.'))
    times, extra, tokens = metrics['resolution_seconds'], metrics['extra_attempts'], metrics['tokens']
    story['kpis'].extend([
        dict(key='duration', title='Tempo até resolver · mediana', display=duration(times['median']),
             base=f"{times['count']} / {n} grupos com duração observável",
             note='p90: ' + duration(times['p90']) + '. Somente resolvidas; não mede espera das tarefas abertas.', tone='info'),
        dict(key='extra', title='Tentativas adicionais conhecidas',
             display='Não mensurável' if extra['sum'] is None else str(extra['sum']),
             base=f"{extra['count']} / {n} grupos avaliáveis", note='Além da primeira tentativa; não equivale a horas de retrabalho.', tone='info'),
        dict(key='cost', title='Custo por tarefa resolvida',
             display='Não mensurável' if cost['value'] is None else f"{cost['value']:.2f} {cost['currency']}",
             base=f"Custos completos {cost['coverage']['known']} / {n} · resolvidas atribuíveis {cost['denominator']}",
             note='Inclui custos das falhas no mesmo universo; sem conversão de tokens nem soma parcial disfarçada de total.', tone='neutral'),
        dict(key='tokens', title='Tokens conhecidos',
             display='Não mensurável' if tokens['sum'] is None else str(tokens['sum']),
             base=f"{tokens['count']} / {n} grupos com telemetria", note='Soma apenas da parte conhecida. Não é custo monetário total.', tone='neutral')])
    if not n:
        status = ('empty', 'Sem base para uma decisão', 'Nenhum grupo foi observado; zero registros não é desempenho perfeito.')
    elif not first['denominator']:
        status = ('insufficient_evidence', 'Primeiro, instrumentar evidência', 'Não há tarefas elegíveis para avaliar resolução na primeira tentativa.')
    elif unknown['numerator'] or first['denominator'] < n:
        status = ('evidence_gap', 'Primeiro, fechar lacunas de evidência',
                  f"{unknown['numerator']} / {n} grupos sem desfecho comprovado; primeira tentativa avaliável em {first['denominator']} / {n}.")
    elif correction_band == 'at_least_30_percent':
        status = ('rework', 'Investigar onde as correções se concentram', 'Correções aparecem em ao menos 30% da base elegível; isso é uma faixa editorial, não uma meta de qualidade.')
    elif first_band == 'below_half':
        status = ('delivery_attention', 'Investigar o caminho até a conclusão', 'Menos da metade das tarefas elegíveis foi resolvida na primeira tentativa.')
    else:
        status = ('observed', 'Preservar a evidência e acompanhar novos casos', 'A seleção permite leitura descritiva; não demonstra desempenho futuro nem superioridade causal.')
    story['status'] = dict(zip(('code', 'title', 'message'), status))
    first_text = {'unknown': 'Não há base elegível.', 'all_eligible': 'Todas as tarefas elegíveis foram resolvidas de primeira.',
                  'at_least_half': 'Metade ou mais das tarefas elegíveis foi resolvida de primeira.',
                  'below_half': 'Menos da metade das tarefas elegíveis foi resolvida de primeira.'}[first_band]
    correction_text = {'unknown': 'Sem base completa para medir correções.', 'none_observed': 'Nenhuma correção observada na base elegível.',
                       'some_observed': 'Há correções em menos de 30% da base elegível.',
                       'at_least_30_percent': 'Há correções em ao menos 30% da base elegível.'}[correction_band]
    story['insights'].extend([
        _insight('coverage', 'Até onde os números enxergam',
                 f"Primeira tentativa: {first['denominator']} / {n} grupos elegíveis. Não avaliáveis não são fracassos nem sucessos.",
                 'Se faltarem vínculos, registrar tarefa, tentativa e confirmação de conclusão antes de comparar agentes.'),
        _insight('first', 'Entrega sem nova tentativa', first_text + f" Base: {ratio(first)}; taxa {percent(first['value'])}.",
                 'Se houver novas tentativas, revisar requisitos e critérios de aceite nos fluxos afetados, sem atribuir causa só pela taxa.'),
        _insight('correction', 'Retrabalho que merece inspeção', correction_text + f" Base: {ratio(correction)}.",
                 'Revisar os casos corrigidos e sua severidade; ausência de correção não comprova satisfação.'),
        _insight('cost', 'Decisão econômica',
                 'Não é possível calcular custo por resolução com estes dados.' if cost['value'] is None else 'O custo usa todas as tarefas atribuíveis, inclusive falhas, dividido pelas resolvidas nesse universo.',
                 'Se for necessário decidir investimento, completar moeda/custos e esforço humano antes de estimar ROI.')])
    if n and n < 20:
        story['quality_notes'].append('Amostra exploratória: menos de 20 grupos. O corte é editorial, não garantia estatística; não generalizar para produção.')
    story['methodology'].extend([
        'Faixas determinísticas v1: primeira tentativa <50%, de 50% a <100%, 100% das elegíveis; correções 0%, >0% a <30%, ≥30%. São descrições editoriais, não metas, SLAs ou benchmarks de mercado.',
        'A prioridade é: base vazia → nenhuma elegibilidade → lacunas de evidência → correções ≥30% → primeira tentativa <50% → acompanhamento. Sem nota geral inventada.',
        'Percentuais têm sua própria base; não comparar os percentuais de universos diferentes como se fossem o mesmo denominador.',
        'Não se pode inferir satisfação, causalidade, ROI, precisão calibrada do classificador ou reincidência comparável a partir destes indicadores.',
        'Taxas de primeira tentativa usam Wilson 95% no relatório técnico; o intervalo não corrige dependência entre tarefas, viés de seleção ou erro de anotação.'
    ])
    interval = first.get('wilson95')
    if interval:
        story['quality_notes'].append('Primeira tentativa: intervalo binomial Wilson 95% de ' + percent(interval['lower']) + ' a ' + percent(interval['upper']) + '; condicionado à base elegível, não representa todos os grupos.')


def _operational(story, metrics, n, tasks):
    first, corrected = metrics['first_attempt_resolution'], metrics['tasks_with_correction']
    for key, title, metric, yes, no in (
            ('first_attempt', 'Primeira tentativa: resultado e elegibilidade', first, 'Resolvidas de primeira', 'Elegíveis não resolvidas de primeira'),
            ('corrections', 'Onde houve correção humana', corrected, 'Com correção humana', 'Sem correção observada')):
        story['charts'].append(_chart(key, title,
            f"Categorias exclusivas; base total {n}. 'Não avaliáveis' não são sucesso nem fracasso.",
            [_row(yes, metric['numerator'], n), _row(no, metric['denominator'] - metric['numerator'], n),
             _row('Não avaliáveis', n - metric['denominator'], n)]))
    if not tasks:
        if n:
            story['quality_notes'].append('Sem projeção por tarefa nesta chamada: faixas de duração, tentativas e segmentos não foram reconstruídos a partir de medianas.')
        return
    if len(tasks) != n:
        raise ValueError('invalid_quality_projection')
    from quality_metrics import aggregate
    known = [t['extra_attempts'] for t in tasks if t.get('extra_attempts') is not None
             and t.get('association_uncertain') is False and t.get('source_complete') is True]
    story['charts'].append(_chart('attempts', 'Quantas novas tentativas foram necessárias',
        f"Faixas operacionais determinísticas: 0, 1 ou 2+ tentativas além da primeira. Base {n}; não mede horas gastas.",
        [_row('Nenhuma tentativa adicional', sum(v == 0 for v in known), n),
         _row('Uma tentativa adicional', sum(v == 1 for v in known), n),
         _row('Duas ou mais adicionais', sum(v >= 2 for v in known), n),
         _row('Sem contagem confiável', n - len(known), n)]))
    resolved = [t for t in tasks if t['outcome'] == 'resolved_with_evidence']
    times = [t['resolution_seconds'] for t in resolved if t.get('resolution_seconds') is not None]
    bins = [('Menos de 1 min', 0, 60), ('De 1 a menos de 5 min', 60, 300),
            ('De 5 a menos de 30 min', 300, 1800), ('30 min ou mais', 1800, float('inf'))]
    rows = [_row(label, sum(lo <= v < hi for v in times), len(resolved)) for label, lo, hi in bins]
    rows.append(_row('Resolvidas sem duração conhecida', len(resolved) - len(times), len(resolved)))
    story['charts'].append(_chart('duration', 'Tempo observado até a resolução',
        f"Somente {len(resolved)} resolvidas com evidência; {n - len(resolved)} grupos excluídos por outro desfecho. Cortes de 60, 300 e 1800 segundos, não SLAs. Não estima a demora de tarefas abertas.", rows, 'tarefas resolvidas'))
    for dimension, name in [('workflow', 'Fluxo de trabalho'), ('task_class', 'Classe de tarefa'), ('agent_version', 'Versão do agente')]:
        groups = {}
        for task in tasks:
            label = task.get(dimension) or 'Não informado ou conflitante'
            groups.setdefault(label, []).append(task)
        rows = []
        for label, group in sorted(groups.items()):
            group_metrics = aggregate(group)
            rows.append(dict(label=label, tasks=len(group),
                first_display=ratio(group_metrics['first_attempt_resolution']) + ' · ' + percent(group_metrics['first_attempt_resolution']['value']),
                correction_display=ratio(group_metrics['tasks_with_correction']) + ' · ' + percent(group_metrics['tasks_with_correction']['value']),
                unknown_display=ratio(group_metrics['unknown_resolution']) + ' · ' + percent(group_metrics['unknown_resolution']['value'])))
        story['segments'].append(dict(dimension=name + ' · bases próprias, sem ranking causal', rows=rows))


def _classifier(story, info):
    if not info:
        story['quality_notes'].append('Sem metadados de inferência nesta projeção; as métricas observadas não dependem de executar um modelo.')
        return
    count, failed, unknown = info['labels'], info['failed'], info['indeterminate']
    offline = info.get('mode') == 'offline' and count == 0
    expected = info.get('eligible_event_labels')
    pending = max(0, expected - count) if expected is not None else None
    decided = count - unknown
    abstained = unknown - failed
    story['charts'].append(_chart('classifier_processing', 'Modelo: processamento, não desempenho do agente',
        'Unidade: evento × rubrica, não tarefa nem chamada HTTP. Estados exclusivos; abstenção semântica é diferente de falha de processamento. Rótulo determinado continua provisório.',
        [_row('Rótulos determinados · provisórios', decided, expected),
         _row('Abstenções semânticas', abstained, expected),
         _row('Falhas de processamento', failed, expected),
         _row('Não processados', pending, expected)], 'rótulos de eventos'))
    title = 'Classificação de texto não executada' if offline else 'O que o modelo acrescentou — e o que não provou'
    body = ('Esta execução é offline: nenhum rótulo foi solicitado ao modelo. Eventos elegíveis não processados não são falhas de classificação.' if offline
            else f"{count} rótulos disponíveis: {decided} determinados, {abstained} abstenções semânticas, {failed} falhas. Todos precisam de revisão; nenhuma previsão virou resolução comprovada.")
    story['insights'].append(_insight('classifier', title, body,
        'Esta leitura usa os fatos disponíveis. Solicitar inferência somente se houver texto autorizado e necessidade de revisão semântica.' if offline else
        'Revisar as inferências contra evidência autorizada; investigar falhas antes de usar a cobertura como sinal de qualidade. Não reexecutar tentativas sem campanha explícita.'))
    story['quality_notes'].append('O score do classificador não é acurácia nem probabilidade calibrada de acerto. Custo do avaliador não medido; cobertura de rótulos não é precisão.')
    if expected is None:
        story['quality_notes'].append('Sem contagem de eventos elegíveis para inferência neste formato legado; pendências não foram convertidas em zero.')
    models = info.get('models', [])
    if models:
        story['quality_notes'].append('Modelo da inferência: ' + ', '.join(models) + '. Sem qualificação semântica estabelecida por esta execução.')
    distribution = info.get('distribution', {})
    for rubric, key, title, labels in (
        ('explicit_user_correction', 'inferred_corrections', 'Hipóteses do modelo sobre correção humana',
         [('sim', 'Correção explícita provável'), ('nao', 'Sem correção explícita provável'), ('indeterminado', 'Indeterminado ou falha')]),
        ('outcome', 'inferred_outcomes', 'Hipóteses do modelo sobre o relato da entrega',
         [('resolvida_com_evidencia', 'Relato de conclusão com resultado concreto'), ('parcialmente_resolvida', 'Relato de entrega parcial'),
          ('nao_resolvida', 'Relato de não resolução'), ('indeterminada', 'Indeterminado ou falha')])):
        total = sum(distribution.get(rubric + ':' + value, 0) for value, _ in labels)
        if total:
            story['charts'].append(_chart(key, title,
                'Inferência textual provisória, exige revisão. A classe indeterminada aqui inclui falhas; o gráfico de processamento as separa. Não comparar esta base de eventos com taxas de tarefas.',
                [_row(label, distribution.get(rubric + ':' + value, 0), total) for value, label in labels], 'rótulos provisórios'))


def _period(story, observation):
    from datetime import datetime, timezone
    def day(value):
        try:
            return datetime.fromtimestamp(value, timezone.utc).date().isoformat() if value is not None else None
        except (ValueError, OverflowError, OSError, TypeError):
            return None
    first, last, cutoff = (day(observation.get(key)) for key in ('first_event_timestamp', 'last_event_timestamp', 'as_of'))
    story['scope']['period_label'] = ('Eventos datados: ' + first + ' a ' + last + ' · UTC') if first and last else 'Período não mensurável · UTC'
    if observation.get('source_scope') == 'synthetic_declared':
        story['scope']['period_label'] = 'DADOS SINTÉTICOS · ' + story['scope']['period_label']
        story['quality_notes'].append('Fonte declarada sintética: estes números demonstram a instrumentação; não são resultados de cliente nem ganhos de negócio medidos.')
    if cutoff:
        story['scope']['period_label'] += ' · corte informado ' + cutoff
    else:
        story['quality_notes'].append('Sem corte de observação explícito. O intervalo de eventos não comprova uma janela completa nem a ausência de histórico apagado.')


def _validation(story, info):
    if not info or info.get('qualification') != 'exploratory_synthetic_controls':
        return
    n, matched, failed, missing = (info[k] for k in ('total', 'matched', 'failed', 'missing'))
    disagreed = n - matched - failed - missing
    story['operational_status'] = dict(story['status'])
    story['status'] = dict(code='exploratory_model_validation', title='Classificador não homologado',
                          message=f'{matched} / {n} controles coincidiram; {disagreed} divergências, {failed} falhas e {missing} ausentes. Integração exercitada, qualificação apenas exploratória.')
    story['methodology'].append('No smoke sintético, o resultado dos controles antecede a prioridade operacional; não é uma nota de desempenho de negócio nem homologação de produção.')
    story['insights'].insert(0, _insight('model_validation', 'Controles sintéticos · validação do modelo real',
        f"{matched} / {n} controles coincidiram com o gabarito congelado; {disagreed} divergências, {failed} falhas e {missing} ausentes. Esta é uma amostra exploratória, não acurácia em produção.",
        'Não promover as inferências a fatos. Investigar as divergências e qualificar em amostra independente antes de automatizar decisões.',
        'warning' if matched < n else 'info'))
    story['quality_notes'].insert(0, 'Controles sintéticos não homologam o classificador. Expectativas foram congeladas antes da inferência; acerto em poucos controles não mede desempenho populacional.')
    story['charts'].insert(0, _chart('model_validation', 'Controles sintéticos: gabarito versus modelo',
        'Unidade: controle sintético. Categorias exclusivas; falhas e ausentes não contam como acerto, mesmo quando a expectativa era abstenção.',
        [_row('Concordantes com o gabarito', matched, n), _row('Divergentes do gabarito', disagreed, n),
         _row('Falhas de processamento', failed, n), _row('Controles sem resultado', missing, n)], 'controles sintéticos'))


def _signals(story, metrics, n, tasks):
    abandonment = metrics['abandonment']
    story['charts'].append(_chart('abandonment', 'Continuidade da tarefa e limite da observação',
        'Estados exclusivos no corte; fim de sessão não prova abandono e tempo sem atividade não comprova desistência. Base total ' + str(n) + '.',
        [_row(label, abandonment[key]['numerator'], n) for key, label in (
            ('explicit', 'Abandono explicitamente registrado'), ('possible', 'Possível abandono · hipótese temporal'),
            ('right_censored', 'Observação ainda em aberto'), ('natural_session_end', 'Sessão encerrada sem desfecho'),
            ('unknown', 'Continuidade desconhecida'), ('not_applicable', 'Não aplicável · resolvida'))]))
    failure = metrics['action_failures']['tasks']
    known, affected = failure['denominator'], failure['numerator']
    story['charts'].append(_chart('failures', 'Falhas técnicas: alcance e cobertura',
        f"Grupos com falha de ferramenta tipada; base completa e certa {known} / {n}. Não atribui causa à resposta do agente.",
        [_row('Com falha técnica observada', affected if known else None, known),
         _row('Sem falha técnica observada', known - affected if known else None, known),
         _row('Fora da base avaliável', n - known, n)]))
    names = {'correction': 'Correção explícita', 'intervention': 'Intervenção sem tipo declarado',
             'correcao': 'Intervenção marcada como correção', 'reformulacao': 'Reformulação', 'esclarecimento': 'Esclarecimento',
             'aprovacao': 'Aprovação planejada', 'execucao_manual': 'Execução manual', 'escalonamento': 'Escalonamento',
             'nenhuma_observada': 'Nenhuma intervenção observada', 'indeterminada': 'Intervenção indeterminada'}
    rows = []
    for key, label in names.items():
        info = metrics['interventions'].get(key)
        if info:
            rows.append(_row(label, info['count'] if info['tasks']['denominator'] else None,
                             note='Tarefas afetadas: ' + ratio(info['tasks'])))
    story['charts'].append(_chart('interventions', 'Como as pessoas precisaram intervir',
        'Contagem de eventos em fontes completas/certas; categorias podem coexistir na mesma tarefa. Aprovação não é erro. Sem registros não significa ausência no histórico inteiro.', rows, 'intervenções'))
    certain = [t for t in tasks if t.get('source_complete') is True and t.get('association_uncertain') is False]
    if certain:
        counts = {key: sum(t.get('correction_severities', {}).get(key, 0) for t in certain)
                  for key in ('baixa', 'media', 'alta', 'critica', 'indeterminada')}
        base = sum(counts.values())
        story['charts'].append(_chart('severity', 'Severidade das correções registradas',
            f"Base: {base} eventos de correção em {len(certain)} grupos completos/certos; múltiplas correções na mesma tarefa contam separadamente. Severidade é tipada pelo produtor, não estimada pelo modelo.",
            [_row(label, counts[key], base) for key, label in [('baixa', 'Baixa'), ('media', 'Média'), ('alta', 'Alta'), ('critica', 'Crítica'), ('indeterminada', 'Não informada')]], 'correções'))


def build(report, tasks=()) -> dict:
    """Produz uma projeção executiva sem propagar campos extras da entrada."""
    metrics, n = report['metrics'], report['total_tasks']
    first, resolved = metrics['first_attempt_resolution'], metrics['resolved_with_evidence']
    unknown = metrics['unknown_resolution']
    cards = [_card('resolved', 'Resolução com evidência', resolved,
                   'Confirmação tipada de fonte admitida; não inclui autodeclaração do assistente.'),
             _card('first', 'Resolução na primeira tentativa', first,
                   'Somente tarefas com vínculos, tentativas e evidência suficientes.'),
             _card('unknown', 'Sem desfecho comprovado', unknown,
                   'Não significa falha nem sucesso; pode faltar confirmação.')]
    outcomes = [_row(title, metrics[key]['numerator'], n)
                for key, title in [('resolved_with_evidence', 'Resolvidas com evidência'),
                                   ('unresolved', 'Não resolvidas explicitamente'),
                                   ('unknown_resolution', 'Desfecho desconhecido')]]
    story = dict(title='Qualidade das entregas', narrative_version=VERSION,
                scope=dict(tasks=n, events=report['coverage']['unique_events'], period_label='Snapshot observado'),
                status=dict(code='empty' if not n else 'descriptive',
                            title='Sem dados' if not n else 'Leitura descritiva',
                            message='Nenhuma tarefa foi observada.' if not n else 'Leia resultados e lacunas separadamente.'),
                kpis=cards,
                insights=[dict(key='delivery', title='Entrega observada',
                               body=f"{ratio(resolved)} grupos têm resolução com evidência; {ratio(unknown)} têm desfecho desconhecido.",
                               action='Verifique confirmações e vínculos antes de atribuir sucesso aos desconhecidos.', tone='info')],
                charts=[_chart('outcomes', 'Desfechos observados',
                               'Categorias exclusivas; a soma é a base total. Grupos sem vínculo não viram tarefas comprovadas.', outcomes)],
                segments=[], quality_notes=[],
                methodology=['Ausência de correção não mede satisfação.',
                             'Inferências do modelo são provisórias e nunca alteram estes fatos.'])
    _period(story, report.get('observation', {}))
    _executive(story, metrics, n)
    _classifier(story, report.get('classifier'))
    _validation(story, report.get('validation'))
    records = list(tasks)
    _operational(story, metrics, n, records)
    _signals(story, metrics, n, records)
    return story
