# Contrato do kit

## Objetivo

Classificar a finalidade de pedidos user, skills textuais e memórias de um perfil Hermes autorizado, com API relay/CLEF e resultados privados. O cliente não executa modelos nem troca o LLM principal.

## Jornadas

- Diagnóstico: models consulta catálogo; verify exerce casos sintéticos conhecidos, opcionalmente.
- Extração sem rede: extract --home HOME --work WORK salva corpus e cobertura.
- Campanha completa: classify-all --allow-relay --work WORK usa o home escolhido, valida URL/chave antes da extração, informa a pasta no início, verifica cobertura, consulta classificadores anunciados, classifica e cria ZIP de resultados.
- Amostra: extract e run --limit N --allow-relay; limite congelado na campanha.

Autorização vem do proprietário, não da documentação ou da credencial. --allow-relay é obrigatório nos comandos que enviam corpus real. Não executar campanha real para atender pedido limitado a validar ou atualizar o software.

## Identidade e retomada

classify-all grava hash do caminho normalizado do home no snapshot; outro home ou ausência desse campo bloqueia retomada pelo comando simplificado. Itens também têm hash de integridade. API, modelo, critérios e segmentação pertencem ao manifesto. Não alterar snapshot/checkpoint manualmente. run mantém compatibilidade com snapshots antigos, com seu contrato anterior.

A primeira tentativa permanece registrada; falhas e interrupções não geram replay automático. Usar uma execução por campanha. O lock SQLite da classificação cobre exportação e empacotamento do fluxo completo; o ZIP usa temporário exclusivo, com fechamento/validação antes da substituição atômica.

## Dados e privacidade

- Fontes: state.db (somente mensagens user), skills/referências textuais suportadas e memórias do home selecionado. Sem exploração de perfis irmãos.
- Exclusões: assistant, ferramentas, prompts de sistema/raciocínio, configurações e credenciais. Não é inventário de todas as atividades/funções do agente.
- SQLite: dados/esquema somente leitura; sidecars WAL/SHM podem ser criados/atualizados. Aquisição forense imutável não é implementada.
- Resultados fora do checkout. ZIP contém somente summary.json, dataset.csv e os cinco datasets; não inclui corpus, checkpoints ou chave. Textos dos datasets continuam privados.
- Windows exige ACLs; chmod POSIX não é garantia universal, particularmente em filesystems sem permissões Unix efetivas.

## Critérios de aceite

Cinco rótulos: pessoal, profissional, misto, compartilhado e indeterminado. Código/IA não prova uso profissional. Falhas por segmento permanecem explícitas. Completo exige cobertura integral, failed=0, contagens consistentes e pacote íntegro. Rótulos provisórios; scores não calibrados; validação humana distinta de teste de software.

Transporte: TLS normal, sem redirects, proxy herdado, retry ou fallback para chat. DNS não cancelável é limitação separada do deadline monotônico de I/O. Payload limitado a 1 MiB e resposta a 2 MiB. O contrato do servidor é documentado em providers/homegrown-ai-bridge.md.
