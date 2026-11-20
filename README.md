# Hermes Domain API Kit

**Classifique pedidos, skills e memórias por finalidade — ou escolha uma rubrica modular para analisar correções, redirecionamentos e insatisfação. Sem instalar modelos no outro PC.**

## Novo: escolha o que classificar

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

## Começar em 3 passos

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
