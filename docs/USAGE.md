# Uso, contrato e diagnóstico

## 1. Preparação sem modelos ou pacotes

Python 3.11+ com SQLite da biblioteca padrão. No Windows use `py -3`/`python`; em Linux/macOS geralmente `python3`. Para subprocessos e redirecionamento no Windows, ative UTF-8 na sessão PowerShell com `$env:PYTHONUTF8 = '1'` antes dos comandos (o CI também o faz). O agente descobre o executável correto, sem alterar configurações globais. Git é opcional se o código vier por ZIP. Instalação de Python, se ausente, é etapa do operador, não download automático de dependências.

Execute a suíte e `python3 cli.py --help`. Escolha diretórios de trabalho privados **fora do repositório**, em filesystem com permissões efetivas. Exemplos abaixo são placeholders: substitua os caminhos e a URL. Os comandos precisam ser executados na raiz do código.

## 2. Configuração por execução

Opções comuns: `--base-url`, `--key-file`, `--model`, `--timeout`. Também são aceitas `HERMES_CLASSIFIER_API_BASE`, `HERMES_CLASSIFIER_KEY_FILE` e `HERMES_CLASSIFIER_API_KEY`; prefira arquivo privado ou prompt local sem eco para a chave, evitando histórico de shell e logs. A variável de chave tem precedência sobre o arquivo: remova uma variável antiga ao trocar a credencial.

Se não houver variável nem arquivo, a CLI pede a chave com `getpass`; não use esse modo em subprocesso sem terminal seguro. Não coloque a chave na linha de comando. O arquivo deve conter apenas a chave CLIENT, sem `Bearer`, aspas ou código; sem symlink. Em POSIX mantenha pasta 700/arquivo 600; Windows exige ACLs apropriadas.

Não há arquivo de configuração do autor para copiar e não se deve executar `.env` ou scripts recebidos como configuração.

```bash
python3 cli.py models --base-url https://api.example.com/api/public/v1 --key-file /caminho/privado/client.key
python3 cli.py verify --base-url https://api.example.com/api/public/v1 --key-file /caminho/privado/client.key --work ../classificacao-privada/api-check
```

Ajuste os caminhos Windows com aspas e o executável Python. `models` anuncia `id` e `task`. Use `--model ID_LITERAL` quando houver mais de um CLEF; nunca presuma que um alias existe. O padrão escolhe `clef-flash-9b-q4-k-m` se anunciado; senão, o único modelo com `clef` no ID. Não há fallback para chat.

`verify` envia cinco exemplos **sintéticos**, verifica seus rótulos e grava `verification/result.json`. O código de saída só é 0 se todos corresponderem; uma requisição HTTP 200 não basta. Nova API/modelo exige diretório de verificação novo. Não enviar corpus real para contornar uma falha de smoke.

## 3. Extração local

```bash
python3 cli.py extract --home /caminho/do/hermes-selecionado --work ../classificacao-privada/amostra
```

`--home` tem precedência sobre `HERMES_HOME`; sem ambos usa `~/.hermes`. Para um perfil específico, informe a raiz correta. A extração não recorre automaticamente em perfis irmãos. Banco ausente/schema incompatível, symlinks e fontes inválidas aparecem na cobertura. `coverage.status=error` bloqueia `run`: não chamar coleta parcial de sucesso.

Revise localmente a cobertura e o snapshot. Não cole `corpus.json` no GitHub/chat. A redação de padrões conhecidos é defesa parcial, não remoção de todos os dados privados. O extrator não executa conteúdo das skills.

## 4. Classificação autorizada

Depois de autorização explícita para enviar a amostra ao relay:

```bash
python3 cli.py run --base-url https://api.example.com/api/public/v1 --key-file /caminho/privado/client.key --work ../classificacao-privada/amostra --limit 10 --allow-relay
```

Para classificar todo o perfil, faça nova extração em **outro diretório** e execute `run` sem `--limit`, somente quando esse escopo estiver aprovado. Não aumente/remova o limite na mesma campanha: o manifesto congela itens, API, modelo e critérios.

Retome com exatamente as mesmas opções. Snapshot e primeiras tentativas são preservados; falhas e requisições interrompidas não são repetidas. Uma nova tentativa intencional exige campanha nova. Não modifique manualmente o manifesto/checkpoint para forçar replay. Use apenas um processo por campanha.

## 5. Entrega local

- `classification/summary.json`: total, categorias, concluídos e falhas.
- `classification/datasets/pessoal.jsonl`, `profissional.jsonl`, `misto.jsonl`, `compartilhado.jsonl`, `indeterminado.jsonl`.
- `classification/dataset.csv`: separador `;`, UTF-8 BOM e escape de fórmulas; contém texto privado.
- JSONL inclui texto, referências e decisões por segmento, portanto **não é artefato público**.
- Manifestos e SQLite suportam integridade e retomada. Não representam certificação da qualidade.

Texto longo é segmentado, sem descartar a cauda; sinais pessoal + profissional em segmentos distintos podem resultar em misto. Falha em segmento mantém o item indeterminado/com erro. Scores não são probabilidades calibradas.

## Contrato HTTP

Autenticação `Authorization: Bearer <CLIENT>` e header `X-Relay-Timeout`, limitado a 120 segundos pelo cliente. Transporte HTTPS com TLS padrão; sem redirects, proxies de ambiente, retries automáticos ou fallback. HTTP só em `127.0.0.1` para fixtures. DNS stdlib não é cancelável; demais etapas compartilham um prazo absoluto.

`GET <base>/models`:

```json
{"data":[{"id":"clef-flash-9b-q4-k-m","task":"classification"}]}
```

`POST <base>/classifications` recebe objeto com `model` (ID literal), `state` (string com documento/contexto), `questions` e `keep_alive: 0`. O contrato exato de critérios está em `study.QUESTIONS`; os cinco rótulos são obrigatórios. Exemplo estrutural de resposta, **sintético**:

```json
{"model":"clef-flash-9b-q4-k-m","answers":{"dominio":{"choice":"pessoal","probabilities":{"pessoal":1.0,"profissional":0.0,"misto":0.0,"compartilhado":0.0,"indeterminado":0.0}}}}
```

O cliente rejeita JSON com duplicatas/não finitos, resposta acima de 2 MiB, payload acima de 1 MiB, campo `error` ou schema inconsistente. Não aceita um contrato de chat como substituto.

## Diagnóstico sem vazar dados

| Sinal | Interpretação/ação |
|---|---|
| `invalid_arguments` | Conferir `--help`; valores não são ecoados para evitar vazamento |
| `http_401` / `http_403` | Operador verifica papel/validade da chave; não buscar credenciais em históricos |
| `http_504` | Pode haver relay sem conector/backend disponível; operador do servidor investiga |
| `timeout` / `transport_error` | Conferir alcance/rede/TLS e serviço; não repetir silenciosamente |
| `classifier_not_advertised` / `choose_clef_model_from_catalog` | Selecionar ID literal compatível do catálogo |
| `incomplete_corpus` | Inspecionar cobertura e fontes, corrigir causa e extrair em campanha nova |
| `campaign_mismatch` | Mudou API/modelo/limite/critério/corpus; criar campanha nova |
| `snapshot_already_exists_use_new_work` | Usar diretório novo, sem sobrescrever snapshot |
| Saída 1 | Smoke semântico ou campanha/coleta incompleta: ler relatório privado |
| Saída 2 | Erro operacional/argumentos/consentimento: corrigir pré-requisito |

Não alterar firewall, portas, serviços do servidor, política de retenção ou modelos como atalho do cliente. Não publicar logs brutos para pedir ajuda.
