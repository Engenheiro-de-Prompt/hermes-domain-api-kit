# Uso e diagnóstico

Execute os comandos na pasta do código. Python 3.11+ e biblioteca padrão; não instale pacotes nem modelos. No Windows substitua python3 por py -3 e use PowerShell com `$env:PYTHONUTF8 = '1'`.

## Escolha o objetivo

| Quero… | Comando |
|---|---|
| Ver os modelos disponíveis, sem histórico | `python3 cli.py models` |
| Testar classificação com exemplos sintéticos | `python3 cli.py verify --work ../teste-api` |
| Somente extrair, sem envio | `python3 cli.py extract --work ../minha-amostra` |
| Classificar 10 itens já extraídos, com autorização | `python3 cli.py run --work ../minha-amostra --limit 10 --allow-relay` |
| Classificar todo o perfil autorizado e gerar ZIP | `python3 cli.py classify-all --work ../minha-classificacao --allow-relay` |

Todos aceitam opções pertinentes de `--help`. A autorização para perfil completo não é necessária para apenas verificar o software. verify é opcional; classify-all não o executa implicitamente.

<a id="credencial"></a>
## Credencial: CLIENT, não AGENT

| Chave | Onde é usada |
|---|---|
| **CLIENT** | Neste kit, no computador consumidor |
| **AGENT** | No conector do computador que hospeda os modelos |
| Backend local | Comunicação interna conector → gateway |
| OpenAI/Hermes | Não é usada por este kit |

Obtenha CLIENT no painel do provedor. Não coloque o valor em chat, argv, código, Git ou documentação. Arquivo deve conter apenas a chave, sem `Bearer`, aspas ou comandos. Em POSIX, use arquivo 0600 em diretório 0700; no Windows restrinja ACLs à conta apropriada. Não use symlink.

### Opção A — terminal local seguro

```bash
python3 cli.py models
```

Sem credencial provisionada, o programa pede `Chave CLIENT (sem eco)`. Digite **no prompt local**, não em uma conversa com o agente. Em subprocesso sem terminal, retorna key_not_provisioned em vez de ecoar ou bloquear aguardando uma chave.

### Opção B — arquivo privado já provisionado

Linux/macOS, substituindo o caminho pelo arquivo real fora do checkout:

```bash
chmod 600 /caminho/privado/client.key
python3 cli.py models --key-file /caminho/privado/client.key
python3 cli.py classify-all --key-file /caminho/privado/client.key --work ../minha-classificacao --allow-relay
```

Windows/PowerShell, com arquivo e ACLs previamente provisionados:

```powershell
$env:PYTHONUTF8 = '1'
py -3 cli.py models --key-file 'C:\Privado\client.key'
py -3 cli.py classify-all --key-file 'C:\Privado\client.key' --work '..\minha-classificacao' --allow-relay
```

Variáveis aceitas: HERMES_CLASSIFIER_KEY_FILE, HERMES_CLASSIFIER_API_KEY e HERMES_CLASSIFIER_API_BASE. **Uma chave no ambiente tem precedência sobre o arquivo.** Se persistir um 401 após trocar o arquivo, confira se há variável antiga. Não mostre os valores para diagnosticar; remova a variável antiga quando necessário. Prefira arquivo privado/vault ao invés de digitar segredo em comando de shell.

## URL e modelo

O endpoint padrão fornecido no pacote está em cli.DEFAULT_API_BASE_URL. Não precisa copiar configurações do computador do autor. Para outro servidor compatível:

```bash
python3 cli.py models --base-url https://api.example.com/api/public/v1
```

Não acrescente /models ou /classifications à base. O kit usa GET /models e POST /classifications, não qualquer contrato OpenAI de chat. Prefere clef-flash-9b-q4-k-m anunciado com task=classification; se houver ambiguidade, use --model ID_LITERAL realmente anunciado. Não inventa aliases nem faz fallback para chat.

## Perfil e escopo

Prioridade: --home explícito → HERMES_HOME → ~/.hermes. Para outro perfil, informe a raiz correta; não selecione uma pasta abrangendo várias contas/perfis.

```bash
python3 cli.py classify-all --home /caminho/do/perfil --work ../campanha-perfil --allow-relay
```

Inclui pedidos user do banco, skills/referências textuais suportadas e memórias. Exclui respostas assistant, ferramentas, sistema/raciocínio, configurações e outros perfis. Extração não executa scripts das skills. A sanitização de formatos conhecidos não garante anonimização; a classificação transmite o texto ao relay hospedado. Só use --allow-relay quando esse trânsito e escopo estiverem autorizados.

Para rever a cobertura antes de enviar, prefira extract seguido de run. coverage.status=error bloqueia a campanha; não chame extração parcial de completa. SQLite é somente leitura de dados/esquema, mas pode coordenar WAL/SHM: não é extração forense de diretório intocado.

## Progresso, interrupção e retomada

No início de classify-all, stderr recebe um evento `campaign` com `work`: guarde essa pasta local. Depois aparecem eventos de progresso com contagens, sem textos nem chave. Caminhos locais podem identificar o usuário; não publique a saída bruta.

Sem --work, é criada uma pasta exclusiva em ~/.local/share/hermes-domain-api-kit/runs/. Repetir sem --work inicia uma **nova** campanha. Para retomar, repita o comando com o caminho informado e com o mesmo home, API, modelo e opções.

O snapshot de classify-all inclui identidade do home; trocar --home ou usar snapshot antigo sem identidade verificável retorna source_home_mismatch. Use o home original ou nova campanha. Não edite o corpus para forçar compatibilidade. Para snapshots legados criados por extract, continue com run, seguindo seu contrato.

Primeiras tentativas, falhas e resultados desconhecidos são preservados e não são reenviados automaticamente. Uma nova tentativa deliberada requer nova campanha. Não apague decisões nem inicie dois processos para o mesmo --work; o lock protege escrita e empacotamento e o concorrente pode retornar OperationalError.

## Resultados

| Caminho relativo à campanha | Conteúdo |
|---|---|
| corpus.json | Snapshot privado e cobertura |
| classification/summary.json | Totais, falhas e contagens por categoria |
| classification/dataset.csv | Planilha com separador ;, UTF-8 BOM e escape de fórmulas |
| classification/datasets/*.jsonl | Cinco datasets; texto, proveniência e decisões por segmento |
| classification_bundle.zip | Apenas resumo, CSV e cinco JSONL; não inclui chave, corpus ou checkpoints |

classify-all gera o ZIP; run exporta os datasets, mas não cria esse pacote automaticamente. ZIP parcial pode existir: só é completo com cobertura integral e failed=0. O arquivo tem CRC verificado antes da entrega; isso prova integridade de empacotamento, não qualidade semântica.

Dados são privados, mesmo em ZIP. Rótulos são provisórios e scores não calibrados. Não publique arquivos para pedir suporte. Sucesso operacional não certifica precisão; revise exemplos do seu acervo antes de automatizar decisões.

<a id="diagnostico"></a>
## Diagnóstico

A CLI mantém códigos estáveis e acrescenta hint em português, sem repetir segredo/argumentos/resposta bruta. Saída 0 significa operação concluída conforme o comando; 1, campanha/extração/smoke incompleto; 2, erro operacional/argumentos/consentimento. Interrupção por teclado pode ter status próprio do sistema.

| Código | Ação concreta |
|---|---|
| invalid_key | CLIENT, não AGENT; sem Bearer/aspas/espaços no arquivo |
| key_not_provisioned | Use --key-file ou prompt local seguro |
| insecure_key_file_permissions | chmod 600 no arquivo POSIX; conferir filesystem com permissões efetivas |
| invalid_key_file | Arquivo regular privado, sem symlink, até 4 KiB |
| http_401 / http_403 | Verificar papel/validade/permissão da chave e variável antiga |
| http_429 | Serviço ocupado/limitado; não há replay automático |
| http_504 | Operador confere conector, polling, backend e prazo no PC dos modelos; não trocar o modelo principal do Hermes |
| timeout / transport_error | Conferir rede/TLS/serviço; preservar a campanha |
| classifier_not_advertised / choose_clef_model_from_catalog | Selecionar um classificador CLEF realmente anunciado |
| incomplete_corpus | Revisar falhas de fonte no snapshot local e criar nova campanha após corrigir |
| source_home_mismatch | Perfil diferente/snapshot sem identidade; usar origem correta ou pasta nova |
| campaign_mismatch | URL/modelo/limite/critério/corpus mudou; manter opções ou iniciar outra campanha |
| snapshot_already_exists_use_new_work | extract não sobrescreve corpus; use pasta nova |
| relay_consent_required | Só se autorizado, acrescente --allow-relay para enviar dados reais |

Não contorne erros removendo validação da chave, habilitando fallback para chat, alterando firewall ou publicando o painel local. Consulte o [contrato da API padrão](providers/homegrown-ai-bridge.md) para payload, TLS e limites.
