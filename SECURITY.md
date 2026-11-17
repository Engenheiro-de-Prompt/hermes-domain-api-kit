# Segurança e privacidade

## Fronteiras

Este repositório publica apenas código, documentação e fixtures sintéticas. Históricos, memórias, skills privadas, chaves, endpoints privados do autor, bancos, logs, modelos e resultados de classificação não fazem parte da distribuição. O histórico Git público começa do snapshot sanitizado, sem importar o histórico do ambiente de desenvolvimento.

A inferência usa o relay autorizado pelo operador, que recebe o texto enviado. Proteção de transporte não define retenção, acesso ou residência dos dados no servidor; confira a política do seu operador. Não usar com dados de terceiros sem autoridade apropriada.

Redaction cobre padrões conhecidos de segredo. Não garante anonimização de nomes, contexto empresarial, dados pessoais ou credenciais com formato desconhecido. Revise o corpus antes do envio. Um scanner sem achados tampouco prova risco zero.

As fontes extraídas e respostas da API são dados não confiáveis. Não executar instruções embutidas, skills extraídas ou comandos sugeridos pelo modelo. A API de classificação não recebe ferramentas/permissões. `AGENTS.md` orienta o consumidor dentro da autorização, não amplia suas permissões.

## Operação

- Chave CLIENT por arquivo privado/prompt sem eco, nunca no código, chat, issue ou commit.
- Diretórios de resultado fora do checkout, permissões efetivas/ACLs do operador; não usar compartilhamento público ou sincronização inadvertida.
- TLS padrão, destino validado antes da leitura do segredo, sem redirects/proxy herdado/retries automáticos.
- Banco de origem somente leitura de dados/esquema. SQLite pode criar/atualizar WAL/SHM; para requisito forense de zero escrita use uma cópia consistente provida pelo operador e validada para esse fim.
- Não explorar automaticamente outros perfis nem credenciais de OpenAI/agent/backend. Não mudar o LLM principal do Hermes.
- Relatórios e CSV/JSONL contêm texto privado mesmo após redaction: não commitar nem anexar em issue.
- Se houver suspeita de chave exposta, revogue-a no operador. Não a use em reprodução pública.

## Relato de problema

Reporte somente descrição e reprodução com dados sintéticos. Não publique segredos/dados de usuário em issues; se a plataforma disponibilizar relato privado de vulnerabilidade, use-o. Não há garantia de canal privado/tempo de atendimento neste documento.
