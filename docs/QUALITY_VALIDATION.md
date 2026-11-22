# Validação executada — incremento de qualidade v1

> Registro inicial offline P0/P1 abaixo. O incremento executivo posterior e o
> smoke no modelo real estão documentados em [QUALITY_DASHBOARD.md](QUALITY_DASHBOARD.md).
> A restrição inicial de não chamar modelos não descreve essa validação posterior.

## Escopo

Checkout existente `hermes-domain-api-kit-public`. Sem commit/push/deploy ou alteração do banco Hermes. Não houve classificação de histórico real, leitura de fontes privadas para fixtures, chamada ao modelo real, migração entre tenants ou treinamento.

## Execuções

| Prova | Resultado observado |
|---|---|
| Baseline antes do incremento: `python3 -m unittest discover -s tests -q` | 139 testes aprovados |
| Suíte completa após implementação, com `PYTHONDONTWRITEBYTECODE=1` | **194 testes aprovados em 19,070 s** |
| Suíte focada `-p 'test_quality*.py'` | 55 testes aprovados em 1,332 s |
| `git diff --check` | Sem erros |
| `ast.parse` em CLI, módulos novos e testes de qualidade | 9 arquivos válidos |
| Scanner simples dos quatro módulos de qualidade | 0 ocorrências de shell=True, pickle.load(s), eval/exec; não substitui auditoria |
| CLI offline no fixture sintético | 22 eventos únicos, 6 tarefas; manifest, JSONL, JSON e HTML produzidos |
| Tempo/RSS da execução offline única | 0,05 s; 24644 KiB; não é benchmark representativo |
| Integração de rede | HTTP **sintético** em loopback; parser, autenticação de teste, CLI, cache e retomada exercitados; nenhuma inferência de modelo real |

Falhas RED foram observadas antes da implementação de: resolução/CLI, correção/segunda tentativa, tenant, ausência de aceite, dedup/conflitos, vínculos/timestamp, intervenções, adapter, janelas de abandono, custos, terminal de fracasso, campanha congelada, enums, tentativas extras, identidade explícita entre sessões, HTML, integração de classificação, orçamento, cobertura, p75 e completude não declarada. A suíte final está verde; isso não mede precisão do classificador.

## Reconciliação da revisão independente

A revisão inicial retornou `passed=false`, com dois bugs P1 e nenhuma preocupação de segurança identificada no caminho normal examinado. Não constitui auditoria geral de segurança.

1. Perder um diretório completo de rubrica permitia repetir inferências. Corrigido com manifesto de classificação que registra as rubricas iniciadas **antes** das chamadas e verifica todos os checkpoints esperados antes da inferência. Na CLI, esse manifesto fica fora de `classification/`, preservando o bloqueio mesmo se a pasta inteira sumir. A perda bloqueia com `checkpoint_incomplete`, sem novas inferências nem recriação; bytes dos arquivos restantes são preservados.
2. Um abandono/fim de sessão antigo prevalecia sobre uma tentativa posterior. Corrigido: atividade posterior invalida o encerramento como estado atual, inclusive entre sessões explicitamente vinculadas. Os eventos históricos continuam na proveniência; uma retomada recente fica censurada à direita.

Os dois casos foram reproduzidos com assertions RED e corrigidos até GREEN. Uma regressão adicional pela CLI também reproduziu a perda da pasta inteira antes de sua correção. A suíte completa acima foi executada após as correções. **Não houve segunda aprovação independente**; esta é a reconciliação do autor respaldada pelos testes.

## Aceites cobertos e limites

- Aceite explícito na primeira tentativa; reparo na segunda; fracasso elegível no denominador.
- Esclarecimento e aprovação planejada não são correção nem falha.
- Novo objetivo não é unido a tarefa anterior; vínculo explícito pode atravessar sessões.
- Silêncio, entrega e alegação assistant não produzem resolução nem satisfação.
- Abandono humano explícito separado de possível, censura à direita e fim natural.
- Falhas de ferramenta não implicam erro de conteúdo.
- Dedup idêntico, conflito de identidade, eventos fora de ordem, timestamps/vínculos ausentes e fontes parciais.
- Custos/tokens ausentes não viram zero; moedas distintas não são somadas. Nenhuma conversão por preço, vencido ou não, foi implementada.
- Score sintético alto não sobrepõe falta de evento de resolução; inferências requerem revisão.
- Dois tenants são recusados; campanha modificada não sobrescreve resultados anteriores.
- Parser malformado, abstenções, cache, matrizes, macro-F1, baseline majoritário, concordância e bloqueio da calibração indevida possuem testes específicos.
- **Não implementado como aceite:** taxa de reincidência comparável entre sessões/agentes, tendências/coortes novas, janelas de trabalho/feriados, atribuição completa de overhead e homologação humana do Clef. O fixture contém duas correções de mesma classe, mas não calcula nem apresenta taxa de reincidência.

## Artefatos reproduzidos

- Entrada: `examples/quality-events.synthetic.json`.
- Saída por tarefa: `examples/quality-tasks.synthetic.jsonl`.
- Agregado: `examples/quality-report.synthetic.json`.
- Dashboard: gerado localmente em `WORK/quality/dashboard.html`; instrução em `docs/QUALITY.md`.

Saída observada: 1/4 resolução na primeira tentativa; 3/6 com resolução por evidência; 2/6 com correção; 2 tentativas extras; 2/6 outcomes desconhecidos; 1 abandono explícito; mediana 180 s; p75/p90/p95 240 s. Custo por resolução null, pois só 5/6 tarefas têm custo atribuível completo. São dados artificiais, não métricas de desempenho de cliente.

As conclusões e fórmulas estão em `docs/QUALITY.md`. As limitações P2/P3 são trabalho futuro, não resultados obtidos.

## Incremento posterior: HTML executivo e smoke real

- Regressão global: **210 testes aprovados em 19,662 s** na execução final.
- Nove testes de narrativa executiva e seis do renderer, além de integração
  da CLI de smoke, exercitam bases, limiares, fonte parcial, entrada vazia,
  privacidade por allowlist, XSS e retomada sem repetir POSTs.
- HTML visualizado em Chromium: desktop de 1280 px e render mobile de 390 px.
  O ajuste de legibilidade foi medido: cartões da primeira linha de 5 para 4;
  a palavra “mensurável” deixou de ser quebrada em duas linhas. Sem overflow
  horizontal do documento no desktop. Tabelas expansíveis abriram normalmente.
- DOM do exemplo público: nove SVGs e zero scripts/links/iframes/imagens/objetos
  externos. CSP bloqueia execução de scripts e conexões; o HTML não requer CDN.
- Modelo real `clef-flash-9b-q4-k-m`: sete registros de resposta, sete decisões,
  **5/7 concordâncias**, zero falhas de processamento e duas divergências
  semânticas contra controles congelados. Não significa acurácia populacional.
- A retomada comparou hashes de `classification/*/results.jsonl`: nenhum mudou.
  Nenhuma previsão textual virou resolução observada; total comprovado no
  smoke permaneceu zero, com sete desfechos desconhecidos.
- Relatório do smoke abre com **Classificador não homologado**. O gabarito
  não foi retunado depois da execução. Resultados públicos são exclusivamente
  de controles sintéticos; respostas brutas ficam fora do repositório.
- Sem commit, push, deploy, mudança de serviço ou alteração do banco Hermes.
- Revisão independente recebida posteriormente com três achados (um P1 e
  dois P2); o encerramento abaixo substitui a situação pendente anterior.
  Correções e regressões do autor não são uma nova aprovação independente.

### Reconciliação da revisão independente

Os três achados foram reproduzidos antes das respectivas correções:

1. Perda simultânea de `classification/` e `classification-manifest.json`
   agora bloqueia antes de criar cliente, consultar catálogo ou recriar cache.
   O manifesto superior registra a classificação iniciada e os controles.
2. Regeneração offline agora preserva a validação congelada, o aviso de
   não homologação e os rótulos disponíveis. Não refaz inferências.
3. Ausência de `smoke-manifest.json` com campanha existente bloqueia sem
   gravar um contrato novo. Não é permitido retunar gabarito após respostas.

Seis regressões novas cobrem os três achados, recuperação legacy e divergência
ou corrupção dos controles. Nos bloqueios, contam GET/POST e verificam os
bytes dos artefatos restantes. A narrativa também distingue cache de ausência
de classificação. Resultado global após a última alteração de código:
**216 testes aprovados em 23,348 s**, com `git diff --check` aprovado.

A campanha Clef anteriormente executada foi regenerada pelo caminho offline,
sem credencial utilizável nem cliente de API: preservou **5/7**, os hashes das
respostas brutas e o HTML público já entregue. Nenhuma nova inferência real
foi solicitada nesta correção. A revisão independente original foi encerrada
com achados; não foi recebida nova aprovação independente após os ajustes.

Comandos, contratos, amostra e limites: [QUALITY_DASHBOARD.md](QUALITY_DASHBOARD.md).
