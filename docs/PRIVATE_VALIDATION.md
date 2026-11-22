# Validação do fluxo privado

Registro de 2026-11-22. Não é certificação de zero retenção do provedor,
calibração do classificador nem resultado de um histórico real.

## Verificado

- Suíte local: **255 testes aprovados**, exclusivamente fixtures sintéticas.
- Integração HTTP de verdade contra servidor de teste: seleção, chave por arquivo,
  orçamento global, cinco rubricas, agregação, HTMLs offline e saída sem sentinelas
  de texto/IDs/workflow. O servidor de teste não é um modelo real.
- Perfil SQLite sintético: planejamento não altera bytes do banco, não grava
  payload e não consulta chave/API. O adaptador não inventa vínculo por tarefa.
- `--dry-run`: contagens mesmo acima do teto; nenhuma pasta, chave ou rede.
- Falta de confirmação após catálogo e deadlines antes do envio/depois da leitura
  bloqueiam todas as requisições seguintes; não deixam relatório parcial de sucesso.
- Destinos equivalentes com `..`, symlinks, arquivos inesperados e modos Git de
  link no índice são recusados. Permissões verificadas no sistema Unix do teste;
  isso não certifica ACLs de outros computadores.
- Publicação auditada nos bytes staged, além do working tree; 90 blobs da história
  anterior foram examinados por padrões de token/chave/caminho de autor, sem
  ocorrências desses padrões. Scanner não prova ausência universal de dados.
- O controle real anterior de sete casos foi regenerado **offline**, preservando
  respostas, HTML e **5/7** concordâncias. Não houve nova inferência para melhorar
  esse placar e ele não é acurácia de produção.

## Integração com serviço real: limite observado

O catálogo local respondeu e satisfez `Cache-Control: no-store`. Uma tentativa
privada usando somente `examples/private-smoke.synthetic.json` encontrou HTTP 502;
uma consulta sintética mínima separada confirmou `classifier_error`. O fluxo
privado bloqueou sem criar sua pasta de resultados. **Isso não é uma campanha
privada concluída nem homologação nova do modelo.** Corrigir o runtime/upstream
é responsabilidade do operador, sem remover os controles do consumidor.

A verificação remota não autenticada respondeu 401 e `no-store`, confirmando
apenas proteção da superfície. Não havia CLIENT remota própria provisionada para
esta validação: **o circuito remoto autenticado não foi homologado nesta entrega**.
Código-fonte, catálogo e headers não substituem essa prova nem auditoria de
fila/banco/expiração/backups. O modo ócio de 48h não foi usado.

O gabarito de integração privada está congelado em
`examples/private-smoke.expected.synthetic.json`, com SHA-256 da fixture. Ele
contém **expectativas**, não inferências que não aconteceram. São poucos controles,
um por rubrica; mesmo concordância integral não homologaria o modelo.

## Reproduzir no ambiente receptor

```sh
python3 -B -m unittest discover -s tests -q
python3 -B tools/check_publication.py
python3 -B cli.py private-analyze \
  --input examples/private-smoke.synthetic.json --tenant synthetic-private-smoke \
  --work "/caminho/privado/controle-novo" --dry-run --timezone UTC
python3 -B cli.py privacy-check --key-file "/caminho/privado/client.key"
python3 -B cli.py private-analyze \
  --input examples/private-smoke.synthetic.json --tenant synthetic-private-smoke \
  --work "/caminho/privado/controle-novo" \
  --key-file "/caminho/privado/client.key" \
  --max-classifier-calls 5 --timezone UTC --allow-relay
```

Use a chave CLIENT do receptor e somente API imediata. Compare os agregados de
`report.json` com o gabarito congelado, preservando divergências. Não invente
resposta nem reutilize o resultado do autor. Execute histórico real somente com
escopo, transmissão, retenção dos agregados e orçamento autorizados.

A configuração de CI faz varredura pública e executa a suíte em Linux, Windows e
macOS; o estado efetivo da execução deve ser consultado em GitHub Actions.
Veja [PRIVACY.md](PRIVACY.md) para os limites e [../COMECE_AQUI.md](../COMECE_AQUI.md)
para o handoff.
