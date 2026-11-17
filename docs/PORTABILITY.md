# Portabilidade e contrato de integração

- Python 3.11+, biblioteca padrão. Scripts relativos ao checkout; nenhum caminho do autor ou token é default.
- Linux/macOS: python3; Windows: py -3. SQLite, urllib, pathlib e csv vêm com Python. O kit não altera shell/profile ou arquivo de configuração Hermes.
- Hermes home: --home explícito > HERMES_HOME > ~/.hermes. Há seleção de um home, não descoberta de todos os perfis. Outras instalações/importações podem exigir apontar o home correto.
- API: GET base/models; POST base/classifications. ID literal retornado como classification, com contrato Clef. Não é um adaptador universal para BART, classificadores arbitrários ou chat.
- Credencial CLIENT em memória após leitura privada. Agent/backend pertencem ao servidor, nunca entram no kit. TLS normal, sem redirects, proxies herdados ou retries.
- O conector e o servidor de modelos são responsabilidade do operador remoto; o consumidor não os reinicia por esta API.
- `--timeout` limita conexão/TLS/upload/headers/body por prazo absoluto. DNS stdlib (`getaddrinfo`) não é cancelável: seu tempo consome o orçamento após retornar, mas pode ultrapassá-lo antes disso. Políticas de rede/TLS do destino precisam de aceite próprio.
- Saídas privadas ficam fora do checkout. Em POSIX usar diretório com permissões efetivas e umask077. Windows depende também das ACLs do usuário; chmod600 não certifica isolamento de conta nesse SO. Não usar volume compartilhado sem controles adequados.
- O leitor tolera colunas opcionais ausentes; schema obrigatório incompatível é erro explícito, não dataset vazio. Histórico disponível e skills em disco não equivalem a serviços externos ou memória de plugins remotos.
- Snapshot não atualiza automaticamente. Nova coleta/campanha preserva anterior.
- Segmentação é por caracteres, conservadora e sem perda, não uma tokenização garantida do backend remoto; se o limite real for menor, erro é preservado. Contexto auxiliar é limitado; pode não resolver continuações.
- Processo interrompido não garante cancelamento do job no relay. A retomada marca resultado desconhecido e não repete a primeira tentativa; operador pode criar nova campanha consciente dessa incerteza.
- Smoke em HTTPS público a partir do host demonstra relay real, não funcionamento já provado numa segunda rede/Windows/macOS. O mesmo comando deve ser exercitado no destino; o kit inclui testes offline para isso.

Referências consultadas: documentação oficial Hermes, sessões, skills, memórias e context files em https://hermes-agent.nousresearch.com/docs . Dados extraídos são somente do home selecionado; não usa raciocínio, ferramentas brutas, autenticação, .env ou system prompts como corpus.
