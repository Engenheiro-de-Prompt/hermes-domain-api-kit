# Feedback automático: duas análises e dashboard offline

## Resultado e pré-requisitos

O comando `feedback-all` prepara um snapshot de feedback de **um perfil autorizado**, executa as duas rubricas independentes **`satisfaction`** (satisfação/insatisfação explícitas) e **`corrections`** (correções/redirecionamentos), deduplica conservadoramente uma projeção derivada e gera agregados CSV/JSON e um dashboard HTML autocontido. Não é dashboard de finalidade pessoal/profissional: o comando legado `classify-all` continua separado.

Você precisa de Python 3.11+, deste checkout, do caminho do seu próprio perfil e de acesso autorizado a uma API compatível com o contrato relay/CLEF. Não precisa das configurações, históricos, controles ou resultados do autor. O kit não instala modelos no consumidor, não altera o LLM principal, não muda serviços e não agenda execuções futuras.

Antes de enviar dados, obtenha uma chave **CLIENT**, não AGENT/OpenAI/backend. Provisione-a em arquivo privado fora do checkout ou use o prompt local sem eco. Nunca coloque a chave no chat ou no comando como valor literal. [Credencial e API](USAGE.md#credencial).

## Tutorial portátil

### 1. Confira o cliente, sem acessar seu histórico ou o modelo

Dentro da pasta do kit:

```bash
python3 --version
python3 -m unittest discover -s tests -v
```

Os testes usam fixtures sintéticas; não certificam qualidade semântica, acurácia histórica ou prontidão de um modelo real. No Windows, substitua `python3` por `py -3`; no PowerShell, configure `$env:PYTHONUTF8 = '1'`.

O calendário padrão é `America/Sao_Paulo` e requer dados IANA do sistema. Se não estiverem disponíveis (comum no Windows), instale **somente dados de fuso**, sem modelos: `py -3 -m pip install -r requirements-timezones.txt`. Alternativamente, use `--timezone UTC` nos comandos de feedback para trabalhar sem esse pacote, com dias/semanas definidos em UTC. A ausência de dados IANA é detectada antes de ler o perfil ou chamar o modelo.

### 2. Execute as duas análises e gere o dashboard

Substitua os caminhos pelos seus. Escolha uma pasta de campanha privada **fora do checkout** e um único perfil que você tenha autorização para ler e transmitir. Execute apenas numa janela autorizada e livre do servidor:

```bash
python3 cli.py feedback-all --home "/caminho/do/perfil" --work "/caminho/privado/campanha-feedback" --allow-relay
```

`--allow-relay` explicita a autorização de transmissão: a extração é local, mas texto do usuário e contexto auxiliar autorizado passam pelo relay para inferência no servidor. Redação automática não garante anonimização. A posse da chave ou este tutorial não autorizam o envio por si sós.

Opções adicionais, quando necessárias:

```bash
python3 cli.py feedback-all --home "/caminho/do/perfil" --work "/caminho/privado/campanha-feedback" --allow-relay --base-url "https://api.example.org/api/public/v1" --key-file "/caminho/privado/client.key" --model "ID_DO_CATALOGO" --cutoff 2026-06-30 --session "ID_DA_SESSAO" --context-chars 1200
```

A URL de exemplo é ilustrativa: omita `--base-url` para usar o padrão do kit ou forneça sua API compatível. `--model` seleciona um ID de classificação anunciado pelo catálogo; não instala modelo nem usa fallback para chat. `--session` restringe a seleção; não use o filtro se quiser o escopo padrão do perfil escolhido. `--context-chars` limita o contexto auxiliar do assistente (padrão 1200). `--cutoff` define a referência temporal do relatório; não torna a campanha um monitoramento de dados futuros.

A extração usa cada mensagem `user` selecionada como candidata a feedback e o último texto `assistant` anterior **da mesma sessão** como contexto auxiliar limitado. Não analisa tools, sistema ou raciocínio. Esse contexto pode ser andamento, não entrega final; sua ausência e seu truncamento permanecem visíveis. Veja a seleção e os limites em [MODULAR.md](MODULAR.md).

### 3. Abra os resultados privados

Saídas canônicas:

| Caminho relativo à pasta `--work` | Conteúdo |
|---|---|
| `unique/dashboard.html` | Dashboard offline autocontido, para abrir no navegador |
| `unique/weekly.csv` | Agregados semanais |
| `unique/report.json` | Relatório agregado estruturado |

Não é necessário servidor web para ler o HTML. A projeção única não apaga nem reescreve o corpus ou os resultados brutos: a deduplicação só une cópias comprovadas; divergências não autorizam fusão arbitrária. Registros físicos e eventos únicos não são a mesma contagem.

**Arquivo gerado não significa campanha bem-sucedida.** Confira cobertura, exclusões, falhas, itens não processados e desconhecidos antes de interpretar os gráficos. Uma campanha parcial deve ser entregue como parcial, não como sucesso por existir HTML.

## Retomada sem repetir inferências

Para retomar, repita `feedback-all` com o mesmo `--work`, perfil e contrato da campanha (API, modelo, seleção e critérios). Tentativas já registradas não são repetidas, inclusive falhas/interrupções: não há retry silencioso. Preserve snapshot, manifestos e checkpoints; não os apague nem os edite para forçar uma nova tentativa.

**Novo histórico exige nova campanha em outra pasta.** Reusar `--work` não incorpora automaticamente sessões ou mensagens futuras. Uma nova pasta também pode provocar novas inferências; inicie-a deliberadamente, com autorização e capacidade do servidor.

## Regenerar relatórios sem API, chave ou perfil

Use somente os dados persistidos da mesma campanha:

```bash
python3 cli.py feedback-report --work "/caminho/privado/campanha-feedback"
```

Para mudar a referência temporal da apresentação:

```bash
python3 cli.py feedback-report --work "/caminho/privado/campanha-feedback" --cutoff 2026-06-30
```

`feedback-report` é **offline**: não precisa de modelo, chave, `--home` ou `--allow-relay`, não relê o perfil e não faz novas inferências. Regenera apenas os relatórios derivados; não corrige falhas de classificação nem preenche histórico ausente.

## Como ler o dashboard

- **Contagens:** mostram os sinais rotulados por semana; não substituem o volume de mensagens processadas.
- **Taxas:** normalizam pelo volume correspondente. Consulte os denominadores e a cobertura; falhas, desconhecidos e não processados não viram decisões válidas ou sucesso.
- **Média móvel ponderada de 4 semanas:** pondera as taxas pelo volume de mensagens na janela de calendário; semanas maiores pesam mais.
- **Mediana móvel de 4 semanas:** usa as taxas semanais válidas na mesma janela, dando igual peso a cada semana válida. Não é a média ponderada com outro nome.
- **Cobertura e comparação de blocos:** ajudam a distinguir oscilação semanal de redução recente; compare blocos completos e equivalentes e considere lacunas e semanas parciais. Semana sem dados não prova ausência de insatisfação.
- **Rubricas independentes:** uma mensagem pode conter mais de um sinal. Não some categorias ou rubricas como se fossem eventos distintos; categorias compostas precisam ser consideradas sem dupla contagem.

Uma queda dos rótulos negativos **não prova melhora sustentada, menos erros objetivos ou satisfação real**. Correção pode ser mudança legítima de preferência ou escopo; ausência de crítica não é satisfação. Rótulos são estimativas provisórias e precisam de avaliação humana representativa para alegações de qualidade. Testes/fixtures sintéticas não qualificam o modelo e controles do autor não representam seu acervo.

## Intervalo observado, ausências e privacidade

O intervalo apresentado corresponde aos dados disponíveis no snapshot e à seleção declarada. **A primeira mensagem observada não comprova a primeira instalação do Hermes**, e a ausência de registros não comprova que nunca houve uso: histórico pode ter sido apagado, estar indisponível, sem data ou fora do escopo. Exclusões, ausências, cobertura incompleta e contexto perdido devem permanecer explícitos, nunca ser convertidos em zeros de sucesso.

Somente o home escolhido é lido; outros perfis não são descobertos nem analisados automaticamente. Credenciais e configurações ficam fora do escopo. SQLite é leitura de dados/esquema, não promessa de pasta forense imutável: sidecars WAL/SHM podem ser criados/atualizados.

Mantenha **home, corpus, checkpoints, CSV/JSON/JSONL e HTML privados**, mesmo quando os relatórios forem agregados. Publique apenas código, documentação e fixtures sintéticas revisadas; não copie contagens, controles ou dados pessoais do autor para demonstrar resultados do consumidor.

[Voltar ao README](../README.md) · [Prompt para outro Hermes](../COMECE_AQUI.md) · [Fluxo modular](MODULAR.md)
