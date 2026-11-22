# Observabilidade por tarefa — contrato v1

## Diagnóstico e plano executado

Alvo: este repositório cliente, não o estudo privado de finalidade nem o servidor de modelos. Baseline executado antes da implementação: 139 testes unittest aprovados. Incremento aditivo, biblioteca padrão Python, fixtures exclusivamente sintéticas, sem mudanças de serviços ou banco Hermes, deploy, push, agendamento ou classificação de histórico real.

| Existente | Incremento | Motivo | Teste | Risco / limite |
|---|---|---|---|---|
| `selection.py`, `extractor.py` | `quality.from_selected` | Preservar proveniência legada | SQLite sintético → seleção → adapter → avaliação | Não inventa task_id ou tentativa |
| `analysis.py`, `api_client.py`, rubricas JSON | `quality_classifier.py`, duas rubricas v1 | Reutilizar parser, isolamento de campanhas e checkpoint | Cliente sintético, erros, retomada e HTTP loopback | Inferência sempre provisória |
| `cli.py` | `quality-report`, `quality-analyze` | Entrada e tenant explícitos | CLI → JSONL + JSON + HTML | Não é uma nova coleta automática |
| Pipeline de feedback existente | `quality.py`, `quality_metrics.py` | Nova projeção por tarefa, sem substituir qualidade por mensagem | Eventos, duplicação, ordens, lacunas e métricas | Depende de vínculo/evidência do produtor |
| Sem gabarito de qualidade por tarefa | `quality_evaluation.py` | Avaliação humana offline | Matriz, abstenção, kappa, calibração bloqueada | Testes não homologam o modelo real |

### Modelo e APIs encontrados

`cli.select_model` prefere **clef-flash-9b-q4-k-m**, anunciado com `task=classification`. Nenhuma troca foi feita. O catálogo continua sendo a fonte da seleção; um `--model` explícito deve constar dele. Se Flash não estiver anunciado, o comportamento legado de seleção é preservado, não uma migração configurada por este incremento.

O cliente usa `GET /models` e `POST /classifications` sobre a base configurada. O serviço local inspecionado registra Clef Flash 9B, GGUF Q4_K_M, contexto configurado 8192 e endpoints `/v1/classifications`/`/v1/systemone`. Não é API de chat. Isso é configuração de código, **não atestado do processo/binário/modelo que está rodando**. Nenhum endpoint real foi chamado nesta entrega.

Retorno consumido: `answers.classificacao.choice` e `probabilities`; `type` e `confidence` opcionais. O parser existente verifica enum, tipos, finitude, intervalo, normalização da distribuição e coerência da escolha. O novo `classifier_score_raw` é o componente da distribuição retornada para a classe escolhida, **não** o campo opcional `confidence`, nem acurácia, nem probabilidade calibrada de acerto. A semântica matemática interna do backend não foi homologada. `score_type=model_class_distribution_uncalibrated` torna essa limitação explícita.

Limites do cliente existente: request 1 MiB, resposta 2 MiB, segmentos de 2400 caracteres, contexto até 1200 caracteres quando usado pelo motor, timeout padrão 145 s; DNS stdlib não é cancelável. Não há fallback/retry implícito. O novo classificador utiliza contexto vazio e marca `context_missing=true`: não finge receber a tarefa completa.

### O que o histórico permite observar

A extração existente consulta `messages`/`sessions`, roles e timestamp opcionais. O snapshot selecionado guarda mensagens user e, para feedback, último assistant anterior na sessão por ID, com flags de truncamento/ausência. Ele **não** fornece automaticamente tarefas, tentativas de conclusão, tools/results completos, tokens, custos, versões ou aceites. Compactação, edição, exclusão e ramificações não são reconstruídas por proximidade temporal.

Por isso, o adapter legado gera eventos com `task_id=null`, `association_uncertain=true`, `source_complete=false`. Agrupá-los por sessão serve somente para uma unidade de inspeção incerta; não os torna uma tarefa comprovada. O adapter não interpreta texto de clientes nem converte predição do classificador em evento de resolução. Integração: `events = quality.from_selected(snapshot, tenant_id=tenant_autorizado, source_id=id_estavel_da_fonte)`; depois `quality.evaluate(events, tenant_id=tenant_autorizado)`. Não há migração da origem; rollback é deixar de usar a projeção aditiva, não restaurar um banco alterado.

## Contrato normalizado

Envelope JSON fechado: `schema_version:1`, `events:[...]`, opcionais `as_of` e `inactivity_seconds` (mapa workflow → segundos). A CLI aceita no máximo 16 MiB por snapshot; dividir volumes maiores em campanhas autorizadas é responsabilidade do operador nesta versão. Não existe descoberta automática de tenants.

Evento requer `event_id`, `tenant_id`, `source_id`, `session_id`, `task_id` (string ou null), `event_type`, `timestamp` (Unix seconds finitos ou null). Campos opcionais e enums fechados estão em `quality.REQUIRED/OPTIONAL/ENUMS`. Tipos booleanos não são números válidos. Chaves extras, conflitos de identidade e mistura de tenants são recusados antes de rede ou inferência. Mensagens de erro não repetem os valores recebidos.

`event_type`: request, attempt, delivery, resolved, unresolved, correction, intervention, abandoned, tool_failure, session_end. `actor`: user, assistant, external, human_reviewer, tool. `source_complete` declara completude da fonte normalizada (ausência significa false: completude desconhecida); o adapter legado sempre declara false. **O produtor é responsável por atestar que um evento tipado representa um fato observado e por autorizar seu escopo.** Digitar `resolved` sobre uma frase qualquer não verifica a realidade. A camada não interpreta texto bruto para produzir esses fatos.

- Identidade física de evento: `(tenant, source_id, event_id)`. Repetição idêntica é deduplicada; mesmo ID com conteúdo diferente é conflito, não atualização silenciosa. Mensagens editadas exigem novo snapshot/revisão explícita.
- Unidade canônica: hash de `(tenant, source_id, task_id explícito)`. Sessões podem compartilhar essa tarefa **somente pelo identificador explícito**; não por horário ou similaridade. task_id ausente produz grupo de sessão incerto.
- `attempt` significa tentativa de concluir o objetivo, não toda resposta do assistente ou chamada de ferramenta. `attempt_id` deve ser estável e único na tarefa.
- Ordenação: timestamp, depois event_id como desempate determinístico. Timestamp ausente ou ambiguidade não se transforma em duração/tentativa comprovada.
- `source_event_ids`, fonte, sessões, dimensões, versão do schema/extrator e `pipeline_run_id` ficam no JSONL privado. Rótulos incluem modelo, prompt_version e classifier_version. Nenhum texto de entrada vai para tasks/report/dashboard; o checkpoint interno da classificação contém texto autorizado e é **privado**.
- Dimensões agent_id, agent_version, workflow e task_class só são preenchidas se os eventos informados não as contradizem; elas não são inferidas.

## Separação metodológica

1. **Eventos:** fatos tipados por produtor autorizado; IDs permitem voltar à fonte sob os controles dela.
2. **Inferências:** duas rubricas versionadas, `quality_correction` e `quality_outcome`; saída tem `origin=classifier_inference`, `is_observable=false`, `review_required=true`. IDs de evidência são âncoras do input (`input_event_reference_only`), não provas externas.
3. **Métricas:** somente funções determinísticas sobre eventos, nunca sobre a confiança do modelo. Mesmo score 1.0 não sobrepõe um fato nem cria sucesso a partir de entrega, silêncio ou autoafirmação.

Predicado de correção: sim / nao / indeterminado para mensagem user isolada; requer correção explícita de algo anterior e distingue pergunta normal, aprovação e mudança de objetivo. Desfecho textual: resolvida_com_evidencia / parcialmente_resolvida / nao_resolvida / indeterminada. Mesmo o primeiro rótulo significa **relato textual provisório**, não resolução real da tarefa. Divergência ou ausência de contexto precisa de revisão.

Saídas do modelo malformadas viram falha/indeterminação via parser existente. Segmentos discordantes abstêm-se. Não há score único inventado para vários segmentos. Falhas de transporte/parser e interrupções são terminais no ledger existente: **retomada não repete chamadas**. Retry automático foi deliberadamente mantido em zero para não alterar contratos históricos; reprocessamento exige outra campanha. Taxonomias A–K completas, evidência semântica por intervalo e contexto multipasso validado ainda não estão homologados.

## Definições das métricas

Toda taxa retorna numerador, denominador, value (null se denominador zero), Wilson 95% e cobertura. Wilson descreve incerteza binomial condicional aos dados; não corrige viés de seleção, dependência entre tarefas ou erro de anotação/classificação.

| Indicador | Definição / elegibilidade / desconhecido |
|---|---|
| `resolved_with_evidence` | Evento resolved ligado à tarefa, de user/external/human_reviewer; autodeclaração assistant não basta. Reparo/reabertura posterior invalida o terminal anterior. Associação incerta não pode resolver a tarefa. |
| `unresolved` / `unknown_resolution` | Não resolução exige terminal unresolved de ator admitido; falta de confirmação, entrega e fim de sessão ficam unknown. Satisfação permanece unknown. Denominador: todos os grupos, inclusive incertos, indicados na cobertura. |
| `first_attempt_resolution` | Numerador: resolução com evidência na única tentativa observada, sem correções. Denominador: tarefas com associação certa, fonte completa, um início, timestamps, tentativas com IDs únicos e terminal ligado a tentativa. Fracasso terminal elegível entra no denominador. Sem esses elementos: null e motivo. |
| `tasks_with_correction` | Tarefas certas/completas com >=1 evento correction de user/human_reviewer / tarefas certas/completas. Dedup impede contar a mesma correção duas vezes. Tipo/severidade permanecem na projeção por tarefa. |
| `no_observed_correction` | Complemento apenas no mesmo universo certo/completo; **não** é satisfação nem resolução. |
| `extra_attempts` | max(0, número de tentativas − 1), somente com tentativas, fonte completa e associação certa; sem isso null. Distribuição e soma não pressupõem desfecho. |
| `interventions` | Contagem e fração de tarefas por enum: correcao, reformulacao, esclarecimento, aprovacao, execucao_manual, escalonamento, nenhuma_observada, indeterminada. Aprovação não aumenta correções/falhas. Correção tipada é contada separadamente, sem duplicar uma mensagem. |
| `action_failures` | Número de tool_failure e tarefas afetadas em fonte certa/completa. Não atribui culpa ao conteúdo gerado. |
| `abandonment` | explicit só por abandoned humano; possible exige janela workflow e as_of configurados; right_censored quando janela ainda não passou; natural_session_end separado. Atividade posterior invalida abandono/fim de sessão anteriores como estado atual, inclusive entre sessões vinculadas; a ocorrência histórica permanece na proveniência. Nenhum timeout vira abandono confirmado. Sem janela/tempo/associação: unknown. É indicador de observação, não estado mental. |
| `resolution_seconds` | timestamp do terminal resolvido − início identificável, não negativo. Somente resolvidas com tempo conhecido. Quantis empíricos nearest-rank x[ceil(p*n)-1], inclusive median (mediana inferior para n par), p75/p90/p95. Não é estimador de sobrevivência e não estima tempo de tarefas abertas. |
| `tokens` | Soma por tarefa somente se todas as tentativas/eventos contabilizáveis informarem tokens e a atribuição for completa/certa. Cobertura acompanhada. Proxy de consumo, sem conversão monetária. |
| `cost_total`, `cost_per_resolved_task` | Soma de TODOS os custos atribuíveis no universo certo, inclusive falhas, dividida pelas tarefas resolvidas com evidência **nesse mesmo universo**. Se faltar custo, moeda, completude ou houver moedas distintas: null, razões e cobertura. Não soma somente as tarefas baratas/conhecidas para simular cobertura total. |

`cost` é telemetria monetária já medida pelo produtor, incluindo os serviços que ele declara atribuíveis ao evento. Não é calculado por tokens, tabela vencida ou preço presumido. Zero precisa estar explicitamente presente. O overhead não atribuído e custos de infraestrutura não são estimados. Tempo ativo, espera de ferramenta/cliente, esforço humano em horas, custo por tarefa iniciada e custo do avaliador continuam não mensuráveis sem telemetria adequada. Não há agrupamento semântico de reincidência nem tendência estratificada por versão nesta slice.

`coverage.fields` conta presentes/não nulos por campo em eventos únicos; mede disponibilidade, não validade semântica. Eventos com fonte parcial, IDs de tarefa ausentes, timestamps ausentes e duplicados têm contadores próprios. `unknown_reason` explica falta de elegibilidade; não reduz ausência a zero.

## Uso e retomada

```bash
# Sem rede, chaves, leitura de perfis ou modelos reais:
python3 -B cli.py quality-report \
  --input examples/quality-events.synthetic.json --tenant synthetic \
  --work /tmp/quality-demo

# Opcional: somente após autorizar o envio do snapshot ao provedor configurado.
# Usar arquivo de chave privado; não colocar chave literal em comando/log.
python3 -B cli.py quality-analyze --input /caminho/autorizado/events.json \
  --tenant tenant-autorizado --work /caminho/privado/campanha \
  --base-url "$BASE_URL_AUTORIZADA" --key-file "$ARQUIVO_DE_CHAVE_PRIVADO" \
  --model clef-flash-9b-q4-k-m --max-classifier-calls 100 --allow-relay

PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -q
```

Saídas em `WORK/quality/`: manifest.json, lock.sqlite, tasks.jsonl, report.json e dashboard.html autocontido. Após inferência: labels.json e classification/ com ledgers/rubricas. Diretórios privados 0700, arquivos 0600 onde suportados; symlinks são recusados no caminho de entrada/saída. HTML não contém trechos nem IDs de evidência, não carrega scripts, fontes ou serviços externos. Não há servidor web nem autenticação nova: abrir/compartilhar artefatos continua sujeito ao controle de acesso do operador. Não compartilhar work/classification, JSONL por tarefa ou chave.

Campanha congela hash de entrada, tenant, schema e extrator; cada motor de rubrica congela também modelo/prompt/base/tamanho. Mudança incompatível recusa reuso. Retomada usa lock SQLite e ledger gravado antes da chamada; uma escrita final interrompida pode ser regenerada sem repetir inferências. `quality-report` pode regenerar offline com labels.json existente e validado por hash. Nova versão de taxonomia pede diretório novo, reaproveitando o snapshot; os motores legados não foram alterados para permitir replay seletivo inseguro. A execução é sequencial, sem batching remoto não validado.

## Avaliação humana e calibração

`quality_evaluation.evaluate(pairs, labels=[...])` aceita pares fechados expected/predicted/score. Produz matriz (linhas verdade, colunas previsão), precisão/recall/F1 por classe, macro-F1, acurácia, distribuições, baseline majoritário e curva score ≥ limiar versus cobertura/acerto entre aceitos. Unknown do gabarito é excluído do denominador avaliável; abstenção com gabarito conhecido conta como erro/FN. Classes sem suporte não são apagadas para inflar macro-F1.

`inter_reviewer_agreement` calcula concordância observada e Cohen kappa; marginais degeneradas retornam kappa desconhecido com motivo. Brier/ECE ficam null para score não calibrado. O modo `calibrated_probability` exige probabilidade legítima de **previsão correta**: é Brier binário de acerto, não multiclasse. Marcar esse modo não ajusta um calibrador nem valida sua origem; só usar depois de estudo independente.

Protocolo operacional, ainda **não executado com humanos**:
1. Definir um tenant autorizado, versões e workflows; amostrar dentro do próprio tenant, nunca entre clientes.
2. Estratificar deterministamente por rubrica/classe prevista, falha/unknown, presença de correção, tamanho e workflow; reservar amostra independente de teste. Registrar seed, IDs selecionados e probabilidade de inclusão para não confundir amostra enriquecida com prevalência populacional.
3. Revisor sem acesso ao score anota apenas evidência disponível, separando correção, esclarecimento, aprovação e mudança de objetivo; ausência de contexto é unknown. Texto minimizado só no ambiente privado autorizado, nunca no relatório agregado.
4. Dois revisores para casos ambíguos e uma subamostra aleatória; adjudicar desacordos com justificativa ligada a IDs. Não usar o próprio agente avaliado como gabarito independente.
5. Medir métricas por classe/workflow/versão; escolher limiar/abstenção em validação separada por predicado. Não há limiar global 0.8.
6. Comparar períodos apenas em estratos comparáveis, preservando composição e cobertura; drift descritivo não comprova causalidade.

### Integridade da retomada de classificação

`quality-analyze` mantém `quality/classification-manifest.json` fora dos diretórios internos de rubrica. Ele congela o contrato e registra as rubricas iniciadas antes da inferência. A ausência de um checkpoint iniciado — inclusive perda integral de `classification/` — bloqueia com `checkpoint_incomplete`, sem replay automático e sem recriar o diretório perdido. Rubricas ainda não iniciadas podem começar normalmente. Uma campanha anterior sem esse manifesto, mas com checkpoints existentes, é recusada como parcial; não há migração ou retry implícitos. Preservar os arquivos restantes para recuperação explícita.

## Exemplo demonstrável e custo de execução

`examples/quality-events.synthetic.json` contém **22 eventos artificiais, 6 tarefas**; não é resultado de cliente nem amostra de produção. A execução offline retornou 4 tarefas elegíveis para primeira tentativa; 1/4 resolvida nela, 3/6 resolvidas com evidência, 2/6 com correção, 2 tentativas extras, 2/6 outcomes desconhecidos, 1 abandono explícito. Mediana até resolução 180 s; p75/p90/p95 240 s. Custos disponíveis em 5/6 tarefas, portanto custo total e por resolução são null. Satisfação e reincidência comprovada não foram medidas.

| Modo | Chamadas de classificação | Custo monetário | Tempo / alcance |
|---|---|---|---|
| Exemplo offline executado | 0 | Não há cobrança de API; custo de infraestrutura não medido | 0,05 s de wall time, 24644 KiB RSS máximo em uma execução local, não benchmark |
| Exemplo com inferência opcional | Estimativa de 5 segmentos para este fixture | null: sem preço/telemetria do avaliador | Não executado contra modelo real; sem latência estimada inventada |
| Regra geral com classificação | Σ ceil(caracteres/2400) por predicado elegível | null até haver telemetria confiável | Teto padrão 100 segmentos; exceder bloqueia antes de cliente/chave/rede |
| Retomada de campanha classificada | 0 novas inferências para tentativas já gravadas | Cobrança anterior não conhecida | GET de catálogo pode ocorrer; quality-report é totalmente offline |

O teste HTTP loopback usa resposta de transporte **explicitamente sintética**, não se apresenta como output real do Clef. Ele valida CLI/parser/ledger/retomada e demonstra que score alto não muda outcome desconhecido. O modelo real e a precisão dos prompts não foram homologados.

## Ganhos, hipóteses, riscos e próximos incrementos

**Implementado:** unidade explícita por tarefa; evidências/unknown; métricas determinísticas com cobertura e denominadores; duas inferências versionadas sem promover relato a fato; tenant obrigatório; dedup/conflitos; congelamento/retomada; relatório mínimo; funções de avaliação humana; adapter legado conservador; testes sem dados privados.

**Ainda não validado:** precisão/recall reais do Clef nessas rubricas, equivalência em lote, calibração/abstenção por predicado, representatividade de qualquer histórico e comparabilidade entre versões. Nenhum ganho percentual de produção ou satisfação pode ser afirmado.

**Riscos/dados faltantes:** fontes legadas sem task_id/attempt_id/aceite; produtor de evento incorreto; custo incompleto; snapshots grandes; sem controle RBAC multiusuário novo nem política de retenção automatizada. Autorização e retenção do ambiente existente continuam necessárias. Nenhum dado foi usado para treino/fine-tuning.

**Próximos passos, separados desta entrega:**
- P0: aprovar e instrumentar produtor de eventos de conclusão e vínculos, sem alterar operação do Hermes por este projeto de análise; testar cobertura real minimizada.
- P1: revisão humana cega estratificada, contexto de tarefa limitado e legítimo, limiares por rubrica e expansão atômica de tipos/severidades/risco. Homologar um lote sintético no endpoint Clef configurado antes de histórico autorizado.
- P2: reincidência com chaves de comparabilidade validadas, separando mesmo objetivo/sessões/agentes; coortes temporais por workflow/versão, calendários operacionais e censura de sobrevivência. O fixture tem erros de classe repetida, mas esta slice **não calcula uma taxa de reincidência**.
- P3: telemetria confiável de custos/tokens/esperas, ledger do próprio avaliador, preços versionados quando aplicáveis, calibração em amostra separada e comparação controlada de versões. Checkpoints distribuídos e reprocessamento seletivo de taxonomia para grandes volumes requerem extensão adicional.

**O que podemos afirmar:** quantas tarefas com vínculo/evidência suficientes foram resolvidas de primeira, quantas exigiram correções, quanto tempo observável levou a resolução e onde o custo não é mensurável. **O que não podemos afirmar:** satisfação real, erro reincidente comparável, ganho causal entre agentes/versões ou custo ausente nos logs.
