# Hermes Domain API Kit

**Classifique pedidos, skills e memórias por finalidade — ou escolha uma rubrica modular para analisar correções, redirecionamentos e insatisfação. Sem instalar modelos no outro PC.**

## Recomendado: análises privadas, gráficos automáticos e payloads só em memória

```sh
python3 -B cli.py privacy-check --key-file "/caminho/privado/client.key"
python3 -B cli.py private-analyze --home "/caminho/do/perfil-autorizado" \
  --work "/caminho/privado/agregados-novos" --key-file "/caminho/privado/client.key" \
  --timezone UTC --allow-relay
```

Executa finalidade, satisfação, correções e inferências auxiliares de qualidade. Planeja o total antes da chave, sem teto artificial padrão; `--max-classifier-calls N` impõe um teto explícito. Grava agregados em `dashboard.html`, `feedback.html`, `report.json`, `narrative.json` e `privacy.json`. Com autorização para recuperação, conserva temporariamente apenas hashes opacos, enum/status por segmento e progresso em `<work>.checkpoint`, nunca textos, prompts ou respostas brutas. Exige perfil explícito e pasta nova fora dele/do checkout; não explora outros perfis, instala modelos ou agenda tarefas. Para política estrita sem decisões persistidas, use `--ram-only` (sem recuperação).

**HTTPS remoto + `no-store` + `X-Relay-Content-Deleted: true` obrigatórios.** Sem confirmação, falha fechada. A fila de ócio/48 horas não é usada. Payloads somente em memória não apagam o histórico original, não cifram agregados, não provam ausência de swap/backups e não são E2EE nem apagamento físico universal. Agregados privados não são anônimos.

**[Contrato, execução, evolução histórica e limites de privacidade](docs/PRIVACY.md)** · **[Prompt completo para outro Hermes](COMECE_AQUI.md)**. O exemplo offline abaixo não exige API; uma campanha real exige chave CLIENT e servidor imediato disponível. Os comandos históricos preservados no restante do README **são persistentes**, não substitutos desse modo privado.

**Retomada:** preserve fonte integral, opções, exports e `<work>.checkpoint`; repita o mesmo comando com `--resume`. Confirmações não são reenviadas. Para lotes longos com repetição de classificação autorizada, use `--retry-transient`; para recuperar a antiga incerteza, acrescente `--recover-uncertain` uma vez. A política at-least-once e o procedimento sem edição de progresso estão no [contrato de recuperação](docs/THROUGHPUT_RECOVERY.md). Sem opt-in, incerteza continua bloqueante. Decisões anteriormente perdidas em RAM não são recuperáveis. `keep_alive` é omitido em lote por padrão; `--keep-alive 0` permanece explícito.

## Novo: qualidade e resolução por tarefa, com evidências

```bash
python3 -B cli.py quality-report --input examples/quality-events.synthetic.json \
  --tenant synthetic --work /tmp/hermes-quality-demo
```

Gera `quality/tasks.jsonl`, `quality/report.json` e `quality/dashboard.html` offline. Resolução na primeira tentativa, correções, tentativas extras, intervenções, abandono qualificado, tempo e custos incluem cobertura e indeterminação. **Silêncio não comprova sucesso nem satisfação.** `quality-analyze` adiciona duas inferências provisórias usando o mesmo motor/Clef, com autorização explícita de transmissão e teto de chamadas; não transforma rótulos em fatos. Históricos legados sem vínculos continuam incertos.

**[Contrato, fórmulas, uso, custo, revisão humana e limitações](docs/QUALITY.md)**. Este é um incremento P0/P1 demonstrável, não homologação do modelo nem implementação integral de reincidência/calibração/custos de produção.

## Relatório executivo automático: leitura de negócio + gráficos + storytelling

```sh
python3 -B examples/generate_quality_demo.py
```

Gera **`examples/quality-dashboard.synthetic.html` no repositório**, sem chave ou rede.
Oito indicadores com denominadores, prioridade de leitura, faixas determinísticas,
ações recomendadas, SVGs, tabelas e recortes por fluxo/classe/versão. O `quality-report`
e o `quality-analyze` passam a gerar também `quality/narrative.json`, a trilha agregada
que explica cada frase. Mensagens brutas não são incluídas no HTML.

**[Uso, interpretação e smoke real pequeno](docs/QUALITY_DASHBOARD.md)** ·
**[Critérios executivos de UX e segurança](docs/QUALITY_DASHBOARD_SPEC.md)**.
O `quality-smoke` usa sete controles sintéticos congelados e o modelo de fato;
expõe divergências no HTML e no exit code. A execução local observada foi **5/7**,
portanto **a integração funciona, mas o classificador não está homologado**.
O dashboard anterior de feedback e seus comandos continuam disponíveis.

## Novo: duas análises de feedback e dashboard em um comando

Para analisar satisfação/insatisfação e correções/redirecionamentos de **um perfil autorizado**, sem montar etapas manualmente:

```bash
python3 cli.py feedback-all --home "/caminho/do/perfil" --work "/caminho/privado/campanha-feedback" --allow-relay
```

Escolha uma pasta privada **fora do checkout**. O comando extrai feedback, executa as rubricas independentes `satisfaction` e `corrections`, aplica deduplicação conservadora numa projeção derivada e gera `unique/dashboard.html`, `unique/weekly.csv` e `unique/report.json` dentro de `--work`. O HTML funciona offline e apresenta contagens, taxas, média móvel ponderada e mediana móvel de 4 semanas, cobertura e comparação de blocos.

É necessário acesso autorizado à API e chave **CLIENT** privada; use `--key-file "/caminho/privado/client.key"` quando provisionada, ou prompt local sem eco. O padrão da API está no kit; `--base-url URL` e `--model ID` permitem seleção explícita. Também são aceitos `--cutoff YYYY-MM-DD`, `--session ID`, `--context-chars 1200` e `--timezone UTC`. O calendário padrão usa `America/Sao_Paulo`; sem dados IANA (comum no Windows), instale `python -m pip install -r requirements-timezones.txt` ou escolha UTC antes da campanha. **`--allow-relay` explicita autorização de transmissão de texto**, não anonimização garantida.

Retome com o mesmo `--work` e contrato: inferências já tentadas não se repetem, nem falhas silenciosamente. Novo histórico exige nova campanha/pasta. Para regenerar somente relatórios, sem perfil, chave, modelo ou rede:

```bash
python3 cli.py feedback-report --work "/caminho/privado/campanha-feedback"
# Opcional: --cutoff YYYY-MM-DD
```

Falhas e ausências não são sucesso. O intervalo observado não comprova primeira instalação nem ausência de histórico apagado; rótulos não provam erro objetivo ou satisfação real. Fixtures não certificam um modelo. O comando não instala modelos, muda serviços, agenda tarefas ou analisa automaticamente outros perfis. Publique apenas código/docs/fixtures sintéticas; home e resultados permanecem privados.

**[Tutorial completo e interpretação do dashboard](docs/DASHBOARD.md)**. O dashboard é de feedback, não de domínio/finalidade. `classify-all` e os comandos modulares abaixo continuam disponíveis.

## Escolha modular do que classificar

- **Fontes independentes:** pedidos, feedback de conversas, skills ou memórias.
- **Seleção:** perfil explícito, sessões específicas e inclusão/exclusão de subagentes.
- **Rubricas JSON:** `domain` (pessoal/profissional e demais classes), `feedback` ou critérios próprios sem editar Python.
- **Extração offline separada da inferência:** prepare agora, use a API somente numa janela livre.

```bash
python3 cli.py rubrics
python3 cli.py extract-selected --rubric feedback --home "/caminho/do/hermes" --work ../feedback-privado
# Execute a próxima etapa SOMENTE quando o servidor estiver livre:
python3 cli.py analyze --rubric feedback --work ../feedback-privado --limit 20 --allow-relay
```

Correção/redirecionamento **não prova erro objetivo do Hermes**. Rótulos são provisórios, com contexto limitado e resultados desconhecidos explícitos. [Guia modular, customização e limites](docs/MODULAR.md).

O fluxo original abaixo continua compatível para classificação de finalidade.

O kit também separa **misto**, **compartilhado** e **indeterminado** para não forçar uma classificação sem evidência. Entrega CSV, cinco JSONL, resumo e um ZIP privado.

## Qual computador faz o quê?

| Computador consumidor — este kit | Computador dos modelos |
|---|---|
| Lê o perfil Hermes escolhido e organiza os resultados | Executa os modelos e devolve as classificações |
| Precisa somente de Python 3.11+ | Precisa do gateway e do conector ativos |
| Usa uma chave **CLIENT** | O conector usa uma chave **AGENT** distinta |

O texto autorizado passa por um relay HTTPS. A inferência é local **ao servidor**, não ao computador consumidor. Este repositório é o **cliente**, não instala nem configura o servidor.

## Legado persistente: começar em 3 passos

### 1. Baixe e confira

```bash
git clone https://github.com/Engenheiro-de-Prompt/hermes-domain-api-kit.git
cd hermes-domain-api-kit
python3 -m unittest discover -s tests -v
```

**Windows:** use `py -3` no lugar de `python3` e, no PowerShell, configure `$env:PYTHONUTF8 = '1'`. Sem Git, baixe **Code → Download ZIP**, extraia e abra um terminal dentro da pasta. Não precisa de pip, GPU, Ollama ou modelos neste PC.

### 2. Tenha uma chave CLIENT

Gere/obtenha uma chave de **cliente** no painel da API. **Não use AGENT, OpenAI ou a chave interna do gateway.** Não envie a chave pelo chat nem a grave no repositório.

O comando pede a chave em um **prompt local sem eco**. Em execução por outro agente/sem terminal, provisione um arquivo privado e acrescente `--key-file "/caminho/privado/client.key"`. [Como configurar no Linux e Windows](docs/USAGE.md#credencial).

A URL pública fornecida no pacote já está configurada: `https://homegrown-ai-bridge.lovable.app/api/public/v1`. Para outro serviço compatível, use `--base-url URL` ou `HERMES_CLASSIFIER_API_BASE`. Nenhuma chave é embutida.

### 3. Classifique

**Este comando envia o escopo completo do perfil selecionado ao relay.** Execute somente com autorização para esse envio:

```bash
python3 cli.py classify-all --allow-relay --work ../minha-classificacao
```

O kit usa `HERMES_HOME` ou, se ausente, `~/.hermes`. Para escolher explicitamente outro perfil, acrescente `--home "/caminho/do/perfil"`. Não explora perfis irmãos.

**Pronto:** veja `../minha-classificacao/classification_bundle.zip`. É um arquivo de **resultados privados**, não uma nova distribuição do código. Não o publique no GitHub.

## O que acontece nesse comando?

1. Valida URL e credencial; chave AGENT é recusada antes da extração.
2. Informa a pasta da campanha e extrai as fontes suportadas, verificando cobertura.
3. Consulta o catálogo e seleciona CLEF anunciado, preferindo Flash quando disponível.
4. Classifica o acervo, exibe contagens e salva checkpoints.
5. Exporta CSV/JSONL/resumo e empacota somente os resultados permitidos.

Não executa exemplos sintéticos antes da campanha. `verify` é um diagnóstico sintético **opcional**, disponível sem ler seu histórico. O modelo principal do Hermes não é alterado.

## Interrompeu? Não comece do zero

Repita o mesmo comando com o **mesmo `--work`, perfil, URL e modelo**. O kit reaproveita decisões registradas sem reenviar inferências já tentadas. Falhas e resultados desconhecidos continuam visíveis; não há retry silencioso.

Sem `--work`, cada execução cria uma pasta nova em `~/.local/share/hermes-domain-api-kit/runs/`; o caminho aparece no início. Guarde-o para retomar. Se alterar a campanha ou quiser deliberadamente tentar uma falha de novo, use outra pasta.

## Algo não funcionou?

| Mensagem | O que fazer |
|---|---|
| `invalid_key` | Use **CLIENT**, não AGENT; arquivo sem `Bearer` ou aspas |
| `key_not_provisioned` | Provisione `--key-file` ou execute em terminal local seguro |
| `http_401` / `http_403` | Verifique validade, papel e permissão da chave |
| `http_504` | O operador verifica conector/backend no **PC dos modelos** |
| `source_home_mismatch` | A pasta pertence a outro perfil ou snapshot antigo; não misture campanhas |
| `campaign_mismatch` | Preserve as opções originais ou escolha outro `--work` |

A CLI devolve `error` e uma orientação `hint`, sem ecoar segredos. [Diagnóstico completo](docs/USAGE.md#diagnostico).

## Quero passar só o link para outro Hermes

Use o [prompt pronto em COMECE_AQUI.md](COMECE_AQUI.md). Ele explica os padrões, o papel da chave e a entrega esperada; não dá acesso automático a dados nem autoriza enviar um perfil por si só.

## Escopo e limites

- **Inclui:** pedidos `user` do `state.db`, skills/referências textuais suportadas e memórias do perfil selecionado.
- **Exclui no fluxo de finalidade:** respostas do assistente, mensagens de ferramenta, prompts de sistema/raciocínio, credenciais/configurações e outros perfis. No fluxo modular `feedback`, somente o último texto `assistant` anterior da mesma sessão pode entrar como contexto auxiliar limitado; não vira tarefa independente. Não é inventário completo de todas as funções executadas pelo agente.
- A redação de padrões conhecidos **não garante anonimização**. CSV/JSONL contêm texto privado.
- SQLite: leitura de dados/esquema; WAL/SHM podem ser criados ou atualizados. Não é aquisição forense de pasta imutável.
- Rótulos são provisórios; scores não são probabilidades calibradas. Testes não certificam precisão no seu acervo.
- API exigida: contrato relay/CLEF (`GET /models`, `POST /classifications`), não qualquer API de chat.

[Uso detalhado](docs/USAGE.md) · [Contrato](docs/SPEC.md) · [API padrão](docs/providers/homegrown-ai-bridge.md) · [Segurança](SECURITY.md) · [Validação](docs/VALIDATION.md) · [Portabilidade](docs/PORTABILITY.md)

## Licença

Nenhuma licença open-source foi selecionada. Visibilidade pública não concede automaticamente uma licença de redistribuição/modificação.
