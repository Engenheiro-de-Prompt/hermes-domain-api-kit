# Privacidade: execução efêmera e limites verificáveis

## O que significa neste kit

**O modo recomendado não cria arquivos contendo prompts, mensagens, contexto ou respostas brutas do modelo.** Com recuperação autorizada, conserva temporariamente apenas enum/status por segmento, hashes opacos e progresso em `<work>.checkpoint`, fora dos exports. Textos permanecem em memória. `--ram-only` desativa esse estado e perde decisões após interrupção. Isso é minimização no consumidor, **não certificação de “zero retenção universal”**. Não usar o checkpoint sem autorização de retenção mínima.

Histórico original, arquivo de entrada, chave CLIENT e agregados deliberadamente salvos continuam existindo. Python não certifica zeragem da RAM. Swap, hibernação, dumps, telemetria, backups e logs do sistema precisam de controles separados. Nada aqui altera discos, apaga históricos ou instala serviços.

## Superfícies da API: não confundir

| Superfície | Retenção/cifragem | Uso neste fluxo |
|---|---|---|
| API imediata `/v1` | HTTPS externo; fila transitória cifrada por consulta no protocolo atualizado; exclusão lógica antes de liberar resposta | Permitida somente com os headers exigidos abaixo |
| Fila assíncrona / modo ócio | Pedidos/respostas cifrados podem aguardar até 48 horas; recibo e chave privada persistem no consumidor | **Não utilizada e não compatível com este objetivo** |
| Loopback `http://127.0.0.1:PORTA/v1` | Não tem TLS, atravessa somente loopback do mesmo computador; não prova a política do runtime local | Opção explícita para operador no computador dos modelos; exige `no-store` |

A documentação do protocolo imediato descreve AES-GCM por consulta e encapsulamento de chave RSA-OAEP efêmero no trecho relay–conector. O cliente deste kit não implementa nem audita essa cifra no servidor. **HTTPS termina no relay: não é E2EE consumidor–modelo.** Bases antigas, backup/PITR e agendamento de limpeza não são comprovados por um header.

## Contrato fail-closed

- Conexão remota somente HTTPS com validação normal de certificado. Sem `insecure`, redirecionamento ou fallback para outra API/modelo.
- URL de API imediata terminada em `/v1`; caminho de modo ócio `/host` é recusado antes da chave.
- Requisições incluem `Cache-Control: no-store` e `Pragma: no-cache`.
- **Toda resposta 2xx** precisa de `Cache-Control` contendo o token exato `no-store`.
- Em HTTPS remoto, exige também **`X-Relay-Content-Deleted: true`**. Ausente/falso: `privacy_confirmation_missing`, antes de ler o corpo.
- O catálogo é verificado antes da primeira classificação. Catálogo 503, autenticação recusada ou confirmação ausente bloqueia o envio de mensagens ao classificador.
- O header expressa a afirmação do aplicativo de que excluiu seu registro lógico. Não prova ausência de cópias, apagamento físico, versão do conector ou integridade de um servidor malicioso.
- Em lote, `keep_alive` é omitido por padrão para não solicitar descarregamento a cada chamada. `--keep-alive 0` conserva a solicitação explícita de descarregamento; `--keep-alive N` solicita segundos de retenção (`-1`: indefinida). A política efetiva é do servidor; nenhuma dessas opções garante zeragem de memória.
- Chave CLIENT por arquivo privado, variável prevista pelo kit ou prompt local sem eco. Nunca em argumentos, chat, repositório, token AGENT ou credencial interna do backend.
- Erros têm códigos fixos; não imprimem corpo remoto, chave ou texto analisado.

Teste sem ler seu histórico nem executar classificação:

```sh
python3 -B cli.py privacy-check --key-file "/caminho/privado/client.key"
```

O resultado `passed` comprova apenas catálogo e headers desta chamada, **não uma auditoria do servidor**. Cada classificação verifica os headers novamente. Não desative o requisito para “resolver” um erro: o operador precisa corrigir o serviço imediato/conector.

## Planejar sem chave, rede ou arquivos

```sh
python3 -B cli.py private-analyze \
  --home "/caminho/do/perfil-autorizado" \
  --work "/caminho/privado/agregados-execucao-nova" \
  --dry-run --max-classifier-calls 100 --timezone UTC
```

Retorna somente contagens e estimativa de chamadas, mesmo se o teto for
insuficiente. Não cria saída, consulta catálogo ou lê a chave. Não precisa de
`--allow-relay` porque não transmite nada. `--dry-run` é recusado pelos comandos
legados. Isto não é teste de disponibilidade da API.

## Executar as análises e gráficos sem arquivos de payload

Pré-requisitos: Python 3.11+, perfil explicitamente autorizado, credencial CLIENT e servidor disponível. Nenhum modelo, pacote criptográfico ou servidor é instalado no consumidor. UTC funciona sem dependências de timezone.

```sh
python3 -B cli.py private-analyze \
  --home "/caminho/do/perfil-autorizado" \
  --work "/caminho/privado/agregados-execucao-nova" \
  --key-file "/caminho/privado/client.key" \
  --timezone UTC --max-classifier-calls 100 --allow-relay
```

A pasta de saída precisa ser **nova**, fora do checkout e fora da árvore do perfil, exceto ao retomar com `--resume`. Sem `--max-classifier-calls`, o orçamento é o plano completo, não 100. Quando explícito, o teto é do conjunto inteiro de segmentos/rubricas, verificado **antes de abrir chave/criar cliente**. Se não couber, informe o bloqueio; não faça truncamento silencioso.

Opções úteis:

- `--sources tasks feedback skills memories`: fontes independentes; esse é o padrão deste modo. `--sources feedback` limita a conversas de feedback e suas inferências auxiliares.
- `--session ID`: filtro exato, repetível, antes de carregar texto; não varre outros perfis.
- `--delegation human`: padrão, exclui subagentes. `all`/`subagent` só por escolha explícita.
- `--context-chars 0`: não transmite contexto auxiliar anterior. Até 1200; redução muda a evidência disponível.
- `--model ID` e `--base-url URL`: seleção explícita, ainda sujeita ao contrato de privacidade e ao catálogo de classificação.
- `--cutoff YYYY-MM-DD`: referência final das janelas do dashboard; deve cobrir os registros datados. Não filtra nem reduz o escopo transmitido.

Sem `--home`, é possível usar **eventos estruturados já autorizados**, sem explorar nenhum perfil:

```sh
python3 -B cli.py private-analyze \
  --input examples/quality-smoke.synthetic.json --tenant synthetic-smoke \
  --work "/caminho/privado/agregados-sinteticos-novos" \
  --key-file "/caminho/privado/client.key" --timezone UTC \
  --max-classifier-calls 100 --allow-relay
```

Não combine `--home` e `--input`. A entrada fornecida já existe por escolha do operador; o kit não cria cópia persistente dela. No modo de perfil, SQLite é aberto somente leitura com visão de WAL vivo; a biblioteca pode atualizar/criar sidecars WAL/SHM. **Não é aquisição forense livre de qualquer escrita na fonte.** Conteúdo e esquema do histórico não são alterados pelo kit.

## Saídas deliberadamente conservadas

| Arquivo em `--work` | Conteúdo |
|---|---|
| `dashboard.html` | Relatório executivo de qualidade, oito indicadores, gráficos, cobertura e narrativa determinística |
| `feedback.html` | Satisfação e correções independentes, calendário semanal completo e tendências conservadoras |
| `report.json` | Agregados, falhas, denominadores, distribuição de finalidade, contrato de rubricas/modelo e cobertura selecionada |
| `narrative.json` | Regras e valores agregados que sustentam a narrativa |
| `privacy.json` | Controles efetivos e limites desta execução, sem alegação de auditoria universal |

Permissões Unix: diretório 0700, arquivos 0600. No Windows, proteja a pasta por ACLs da conta. **Não há cifra caseira ou senha embutida.** Se a política exige criptografia em repouso, use volume previamente protegido (por exemplo, BitLocker/LUKS) e confira backups. O kit não pode certificar a configuração desse volume nem a integridade do sistema operacional.

Não saem texto, contexto, mensagens, hashes por item, IDs de sessão/tarefa/tenant, scores por item, resposta bruta ou nomes livres de workflow/agente. As dimensões livres são suprimidas neste modo para evitar transformá-las em vazamento por rótulo de gráfico. Datas são agregadas em dias/semanas. **Agregados pequenos ainda podem reidentificar e revelar informações sensíveis; não são anônimos nem destinados automaticamente ao GitHub.**

## Qualidade, histórico ao longo do tempo e limites

As rubricas `domain`, `satisfaction`, `corrections`, `quality_correction` e `quality_outcome` continuam independentes. O relatório conserva modelo escolhido, versões/hashes das rubricas, timezone e critérios gerais de seleção. Falha de chamada fica `error`/desconhecida, nunca satisfação positiva nem conclusão. Rótulos são provisórios e não homologam o modelo.

Pedidos e respostas legados não contêm necessariamente vínculos confiáveis de tarefa, tentativa ou resolução. O adaptador mantém `association_uncertain=true` e fonte incompleta: **não inventa resolução na primeira tentativa, custo zero ou abandono por silêncio**. Para métricas operacionais observáveis, forneça eventos explicitamente vinculados, como no contrato de `docs/QUALITY.md`.

Para atualizar ao longo do tempo, execute novamente, conscientemente, em **outra pasta**, sobre o histórico atual autorizado. Cada relatório reprocessa seu escopo inteiro e inclui sua série semanal. Não some relatórios de janelas sobrepostas e não confunda mudança de modelo/rubrica/coorte com melhora do Hermes. Não há merge incremental com garantia exatamente uma vez, pois IDs/decisões por mensagem não são conservados. Verifique manualmente escopo/modelo antes de comparar execuções.

Para recuperar, repita o mesmo comando com `--resume`, preservando fonte integral, modelo, opções, exports e `<work>.checkpoint` (ou `--checkpoint-dir` explícito). Lock exclusivo e contrato congelado impedem mistura de campanhas. Cada envio é registrado como unknown antes da chamada; confirmações são sincronizadas antes da próxima. Unknown pausa globalmente, sem replay mesmo de pendentes posteriores. Só 429 HTTPS com headers de privacidade e corpo autenticado `error.type=capacity_busy`, `admission=not_started`, `limit_scope=concurrency`, `retry_after` inteiro 1..60 permite voltar a pending e tentar **apenas em retomada explícita**, nunca em loop automático. 429/503 isolados não provam rejeição anterior à execução.

Ao concluir, arquivos, diretório dos exports e seu pai são sincronizados antes de criar `completed.json` e retirar `state.json` com labels. O marcador antirreplay permanece fora dos exports. Retomada concluída valida todos os hashes antes da limpeza idempotente; não precisa de API/chave. Não apague checkpoint nem use outra pasta para contornar incerteza. Isso não recupera decisões perdidas em campanhas RAM-only antigas. Leia [recuperação e limites](THROUGHPUT_RECOVERY.md).

## Comandos legados são persistentes

`classify-all`, `feedback-all`, `analyze`, `quality-analyze`, `quality-smoke` e extrações explícitas continuam compatíveis, **mas podem gravar texto, respostas, snapshots, decisões e checkpoints**. Não são o caminho de minimização de retenção. `quality-report` pode criar projeções por tarefa mesmo sendo offline. Só use esses fluxos se essa conservação for explicitamente necessária e autorizada.

O modo privado não apaga resíduos de campanhas antigas, perfis originais, filas do servidor nem arquivos de terceiros. Inventariar e excluir esses dados exige escopo próprio; exclusão lógica não certifica apagamento físico.

## Lacunas que exigem o operador

- Confirmar implantação do protocolo imediato e versão compatível do conector; não inferir disponibilidade pelo código-fonte.
- Confirmar chamada/agendamento real de expiração, filas legadas, exclusão em falha/interrupção, backups/PITR e políticas do provedor. Ter função de limpeza no código não prova que ela roda.
- Conferir logs, cache, swap, hibernação e dumps em consumidor, relay, conector e backend de modelos.
- Se o requisito for nenhuma gravação transitória ou E2EE de ponta a ponta, **esta API imediata e seu header não comprovam esse requisito**. Não trocar silenciosamente para a fila cifrada de 48 horas.
- Provisionar uma chave CLIENT própria para cada destinatário; código público não distribui credenciais ou autorização para dados.
