# Recuperação privada: capacidade, interrupção e limites

## Estado atual

`private-analyze` mantém textos, prompts, contexto e respostas brutas somente em
memória. Quando a retenção mínima está autorizada, registra temporariamente
**enum/status por segmento, hashes opacos e progresso** em `<work>.checkpoint`,
ou `--checkpoint-dir` explícito, fora de perfil, checkout e exports. Isso não é
RAM-only: use `--ram-only` se a política proibir persistir decisões; nesse caso
interrupção perde progresso e não há recuperação. Não existe importação de
respostas já perdidas em campanhas antigas, nem atualização de processos remotos
por editar o kit local.

## Planejar e executar

Primeiro use `private-analyze ... --dry-run --timezone UTC`: não abre chave,
cliente ou rede nem grava arquivos. Sem `--max-classifier-calls`, o orçamento
é o plano inteiro; um teto explícito insuficiente bloqueia antes do cliente,
nunca trunca fontes, segmentos ou rubricas. Outros comandos de qualidade podem
manter seu padrão 100.

Execute com fonte e retenção autorizadas, `--work` novo fora do perfil/checkout,
`--allow-relay`, chave CLIENT privada e opções de seleção explícitas. As cinco
rubricas permanecem independentes. Zero elegíveis de uma rubrica não autoriza
fabricar eventos. Labels inferidos são provisórios, não fatos ou homologação.

## Retomar sem replay

Preserve **fonte integral, todas as opções, modelo, URL, exports e checkpoint**.
Repita exatamente o comando original adicionando `--resume`. Não crie pasta
nova para contornar uma incerteza, nem edite/remova estado. Fonte ou contrato
alterados, checkpoint ausente/corrompido e lock ocupado bloqueiam antes da chave.

- Antes de enviar, o segmento é sincronizado como `unknown` (write-ahead).
- Ao receber decisão válida, `ok` e enum são sincronizados antes do próximo envio.
- Confirmados são reconstruídos sem inferência. `unknown` é sticky e pausa
  globalmente: nem os segmentos posteriores pendentes são enviados.
- 429/503/504/timeout isolados **não** comprovam rejeição anterior à execução.
- Exceção estrita: somente HTTPS com validação TLS normal, cliente
  `require_privacy`, headers `no-store` e `X-Relay-Content-Deleted: true`, status
  **429** e corpo `error.type=capacity_busy`, `admission=not_started`,
  `limit_scope=concurrency`, `retry_after` inteiro entre **1 e 60** constituem
  prova de não admissão. O cliente não faz retry; o journal deixa esse segmento
  `pending`, pausa o lote e permite nova tentativa só em `--resume` explícito.
  Header local isolado não basta; HTTP loopback não autentica essa prova.

Exit 1 é parcial, com confirmações/incertos/pendentes e distribuições apenas de
itens `status=ok`. Rubrica nunca enviada tem distribuição vazia, não falsas
abstenções semânticas. Não reduza rubricas nem aumente concorrência para ocultar
indisponibilidade.

## Exports e limpeza

Após todas as confirmações, o consumidor grava atomicamente exports com LF,
sincroniza arquivos, diretório de saída **e seu pai**, inclusive em retomadas,
e só então grava `completed.json` e remove `state.json` com labels temporários.
O marcador antirreplay permanece. Na retomada concluída, valida os cinco hashes
de exports antes de finalizar limpeza idempotente; não consulta API nem chave.
Exports ausentes/alterados bloqueiam, nunca autorizam reclassificação.

Isso é protocolo de durabilidade POSIX, não prova de queda de energia real nem
garantia sobre hardware, swap, dumps, backups ou ACLs Windows. Agregados e estado
mínimo continuam privados; não publicar nem enviar pelo chat.

## Retenção de modelo e diagnóstico

Em lote, `keep_alive` é omitido por padrão. `--keep-alive 0` continua explícito;
`N` solicita segundos e `-1` retenção indefinida. A política efetiva é do servidor;
isso não mede ganho de throughput nem certifica zeragem de memória. Não mudar
serviços, descarregar modelos compartilhados ou remover guards por timeout HTTP.

Comandos legados persistentes continuam disponíveis, mas conservam texto,
contexto, IDs e respostas. Não são fallback automático desta recuperação mínima.

### Adaptador legado offline (somente com autorização de conteúdo persistente)

Para uma campanha `feedback-all` já congelada, o adaptador abaixo valida o seal
antes de criar exclusivamente uma entrada de `quality-analyze`. **Grava texto e
IDs**, não é parte de `private-analyze`. Execute uma única vez, não para retomar:

```sh
python3 -B -c 'import json,os,sys; from pathlib import Path; from study import digest; from quality import from_selected; os.umask(0o077); s=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")); seal=s.pop("snapshot_sha256",None); assert seal and digest(s)==seal and digest(s["items"])==s.get("items_sha256") and s.get("coverage",{}).get("status")=="ok", "snapshot_integrity_failed"; e=from_selected(s,tenant_id="selected_profile",source_id="selected_profile"); p=Path(sys.argv[2]); f=p.open("x",encoding="utf-8"); json.dump({"schema_version":1,"events":e},f,ensure_ascii=False,allow_nan=False); f.write("\n"); f.close()' \
  /privado/campanha/feedback/corpus.json /privado/campanha/quality-input.json
```

Retome `quality-analyze` só com a mesma entrada e work; não recrie a entrada.
O adaptador de perfil produz user, portanto outcome sem elegíveis não deve
receber entregas assistant inventadas.
Reporte comandos/exit codes realmente observados, caminhos privados, cobertura,
falhas, modelo/contrato e chamadas novas na retomada. Testes sintéticos offline
não comprovam produção, qualidade semântica ou execução com dados reais.
