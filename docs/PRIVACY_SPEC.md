# Contrato da execução privada v1

## Escopo autorizado

Adequar o consumidor público de análises, preservar comandos existentes, documentar o handoff e publicar somente código, documentação e controles sintéticos. Não atualizar conectores/servidores, instalar dependências, alterar discos ou apagar históricos originais neste fluxo.

## Decisões

- `private-analyze` é a entrada recomendada para novos consumidores. Exige uma fonte explícita (`--home` OU `--input` estruturado com `--tenant`), autorização de transmissão e orçamento global validado antes da chave/cliente.
- Extração, payloads e respostas brutas ficam em objetos Python. Recuperação autorizada usa somente hashes opacos, enum/status por segmento e progresso temporário fora dos exports; sem snapshot textual, SQLite derivado, JSONL, ZIP ou recibo. `--ram-only` desativa recuperação.
- Satisfação, correções, finalidade e qualidade continuam análises distintas. Inferência não altera fatos observados. Sem vínculo explícito de tarefa, resolução por tentativa fica desconhecida.
- Saída deliberada: diretório privado novo, com HTML e JSON agregados, calendário semanal e rubricas fixas. Nunca IDs, nomes de sessões, texto, caminhos de fontes, rótulos livres de workflow ou scores por item. Agregados ainda são dados sensíveis, não anonimização.
- Fonte original permanece intacta como conteúdo. SQLite vivo pode atualizar sidecars WAL/SHM durante leitura, conforme contrato do extrator existente; não é aquisição forense sem escritas.
- A API imediata é separada do modo assíncrono/ócio. Fila de 48 horas e recibos privados não são compatíveis com este objetivo e não serão usados.
- HTTPS remoto com validação TLS, sem redirecionamentos. Requisições e respostas `no-store`; respostas remotas só são aceitas com `X-Relay-Content-Deleted: true`. Ausência gera erro fixo, sem corpo liberado nem fallback.
- O header é uma declaração do aplicativo remoto sobre exclusão lógica antes da entrega, não auditoria independente do banco, E2EE nem apagamento físico. Loopback HTTP só serve quando executado no computador do modelo, com operador responsável pelo runtime e controles locais.
- Sem retry automático, agendamento ou importação de outros perfis. `--resume` reutiliza confirmações sob contrato congelado; unknown pausa globalmente e nunca é reenviado. Rejeição HTTPS 429 com privacidade e prova autenticada de não admissão permite pending até retomada explícita. Labels temporários são retirados só após exports duráveis; marcador antirreplay permanece.
- Sem promessa de apagar RAM Python, swap, dumps, backups, histórico deliberado ou agregados salvos. Criptografia de disco e controles de memória são responsabilidade explícita do ambiente, não serão fingidos com codificação ou cifra caseira.

## Verificação

TDD com fixtures sintéticas; orçamento antes do cliente; validação dos headers antes de ler corpo; ausência de payloads nos arquivos e stdout; múltiplas semanas e desconhecidos preservados; renderer real exercitado; integração real pequena quando endpoint/credencial autorizados estiverem disponíveis. Erro de disponibilidade não será convertido em inferência fictícia. Sanitização e revisão independente precedem commit/push; publicação é verificada no remoto e na CI.
