# Recuperação de campanhas após falhas transitórias

## Contrato entregue

`private-analyze --retry-transient` permite repetição **at-least-once**, limitada e
com backoff, para 502/503/504/timeout/transporte e rejeição de capacidade
comprovadamente não iniciada. Nunca reenvia segmentos confirmados. Para a
primeira retomada do checkpoint legado incerto, repetir o comando original,
na mesma pasta, acrescentando `--resume --retry-transient --recover-uncertain`.
Não editar progresso nem começar outra campanha. Recuperações seguintes usam
`--resume --retry-transient`. Preservar fonte, modelo, seleção e orçamento.

Um 504 não prova que o servidor deixou de processar. A política pode repetir
trabalho/cota e variar o rótulo de uma tentativa cuja resposta se perdeu; só a
primeira resposta válida confirmada é aceita e contada. Auth, privacidade,
checkpoint, contrato e persistência continuam bloqueantes. Após exaustão local,
a lacuna fica explícita e segmentos independentes continuam; um parcial não
é entregue como completo. Não há promessa de disponibilidade ou acurácia 100%.

## Evidências reproduzidas

- Suíte isolada de publicação: **299 testes aprovados**, sem skips. A fixture
  normaliza o temporário do sistema (inclusive aliases de macOS) antes de
  entregar o caminho ao Journal; a proteção de produção contra links permanece
  inalterada e ativa.
- CLI + HTTP loopback, **10.560 classificações sintéticas**: parada inicial
  após **304 confirmadas**, cinco HTTP 504 injetados, retomada na mesma campanha,
  **10.560 confirmadas**, zero reenvios do prefixo e zero novas chamadas depois
  de concluído. Fonte/credencial sintéticas; não representa o histórico real.
- O harness `tests/verify_campaign_transient_recovery.py --workdir <temporário>`
  usa somente dados sintéticos, fronteira HTTP local e CLI em subprocessos. Não
  contém modelo/serviço/chave reais. Sua prova de transporte não mede semântica.
- Integração separada pelo relay público/API e modelo CLEF-Flash real: quatro
  classificações de um controle sintético, quatro confirmações, zero falhas,
  ambos os HTMLs gerados e headers de privacidade obrigatórios preservados.
- Revisão independente verificou prefixo de 304, opt-in legado separado,
  corrupção, fsync antes/depois da rede, auth/privacidade e falso sucesso parcial.

## quality-smoke

O timeout histórico de 30s não se reproduziu com o handler original. A fixture
herdava 145s por HTTP dentro de um watchdog de 30s. Foi adicionado timeout
**apenas na fixture**, sem ampliar o watchdog ou reduzir o prazo de produção.
Uma resposta sintética travada agora produz falha explícita/export durável;
retomada não reenvia os sete controles. Não se atribui causa histórica não
comprovada nem se oculta uma falha real de classificação.

## Limite de acesso

Nenhuma campanha ou perfil real do consumidor foi aberto, modificado ou
reiniciado. Preservar 304 confirmações foi provado em reprodução sintética;
a recuperação do checkpoint remoto depende de o consumidor executar a retomada
oficial com esta versão. Código não substitui entrega dos HTMLs reais finais.
