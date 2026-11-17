# Hermes Domain API Kit

**Entregue este link a outro Hermes e uma API de classificação compatível.** O agente prepara a execução no computador de destino, extrai as fontes locais autorizadas e classifica sua finalidade sem instalar modelos ou trocar o LLM principal do Hermes.

Categorias: **pessoal · profissional · misto · compartilhado · indeterminado**.

## Comece aqui

1. Copie o [prompt pronto para outro Hermes](COMECE_AQUI.md).
2. Informe a **URL base HTTPS** da sua API e disponibilize uma **chave CLIENT por arquivo privado ou prompt local sem eco** — não no chat nem neste repositório.
3. O Hermes lê `AGENTS.md`, verifica Python, testa o cliente e a API com exemplos sintéticos, extrai o perfil escolhido e executa a amostra ou campanha autorizada.
4. Receba o resumo e os caminhos privados dos cinco datasets e do CSV.

Não há conta, endereço de servidor, modelo instalado ou chave do autor embutidos. Só Python **3.11+** e biblioteca padrão. Git serve para clonar; um ZIP do GitHub também funciona. Em Windows, use `py -3` ou `python` no lugar de `python3`. Não instale pacotes com pip.

```bash
git clone https://github.com/Engenheiro-de-Prompt/hermes-domain-api-kit.git
cd hermes-domain-api-kit
python3 -m unittest discover -s tests -v
python3 cli.py --help
```

## O que entra e sai

| Entrada local selecionada | Tratamento |
|---|---|
| `state.db` do Hermes | Pedidos `user`, com referências; não respostas do assistente/ferramentas |
| `skills/` | Markdown e referências/templates textuais suportados; nenhum script executado |
| `memories/MEMORY.md`, `memories/USER.md` e variantes na raiz | Fatos/seções de memória |

Não explora perfis irmãos, não instala skill global, não lê `.env` ou configuração de autenticação e não importa credenciais de outro agente. Extrair uma conversa pode incluir dados sensíveis escritos pelo próprio usuário: a redação automática é limitada a formatos conhecidos e **não é anonimização garantida**.

Saídas **fora do checkout**: `corpus.json`, cobertura, checkpoints SQLite, `classification/summary.json`, `classification/dataset.csv` e `classification/datasets/<categoria>.jsonl`. Todos os rótulos são provisórios. Falhas permanecem no relatório, sem retries silenciosos.

## API exigida

É um cliente do contrato **relay + classificação CLEF**, não de qualquer endpoint OpenAI/chat. A API precisa oferecer `GET /models`, modelos anunciados com `task=classification` e `POST /classifications`. Consulte o [contrato e comandos completos](docs/USAGE.md).

Uma nova URL/chave da mesma família não exige editar código. Outro protocolo ou tipo de classificador exige um adaptador explícito; o agente não deve inventar respostas nem fazer fallback para chat.

## Privacidade e limites

- Inferência acontece no servidor remoto. O texto autorizado passa pelo relay hospedado: isso **não** é processamento exclusivamente local.
- `extract` é local; `run` exige `--allow-relay`. O ensaio `verify` envia apenas exemplos sintéticos.
- SQL em modo somente leitura de dados/esquema. O SQLite pode criar/atualizar sidecars WAL/SHM; não é aquisição forense de pasta imutável.
- Não há homologação automática de qualquer API, hardware ou qualidade de classificação. O smoke não substitui revisão humana.
- [Segurança](SECURITY.md) · [Uso e diagnóstico](docs/USAGE.md) · [Validação](docs/VALIDATION.md) · [Portabilidade](docs/PORTABILITY.md) · [Contrato de escopo](docs/SPEC.md)

## Licença

Nenhuma licença open-source foi selecionada nesta publicação. A visibilidade pública, por si só, não concede uma licença de redistribuição/modificação. Não presumir MIT ou outra licença.
