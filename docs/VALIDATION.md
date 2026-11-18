# Validação e limites

## Reprodução offline

```bash
python3 -m unittest discover -s tests -v
```

Testes stdlib com fixtures: HTTP real em loopback, SQLite sintético, extração, cobertura, redação por padrões, JSON estrito, limites/deadline, bloqueio de redirects/proxies, checkpoints, retomada, classificação completa e pacote ZIP. As regressões de entrada cobrem CLIENT versus AGENT, orientação segura, autorização explícita de envio e identidade do perfil. Testes não leem perfis/configurações reais nem usam chave do serviço.

O CI executa o mesmo comando em Linux, Windows e macOS; a conclusão associada ao commit no GitHub é a evidência remota. Bits POSIX são conferidos somente em POSIX; Windows requer ACLs e testes de empacotamento próprios, não chmod como prova de privacidade.

## Origem e integração

Esta atualização incorporou partes revisadas do pacote de código fornecido pelo proprietário e corrigiu entrada, documentação e empacotamento. O fluxo legado de transporte e extração tem evidências históricas de uso pelo relay público com corpus sintético; isso não homologa automaticamente a nova campanha completa em todos os computadores.

A validação desta atualização usa fixtures e cópia limpa. Não classifica o histórico real do proprietário para testar a publicação. O comando verify permite um smoke público sintético opcional quando o operador autorizar; classify-all não o dispara implicitamente.

## Não confundir

- Suíte verde ou ZIP com CRC íntegro não certifica precisão dos rótulos.
- Cliente no PC dos modelos acessando hostname público não comprova origem em outro computador/rede.
- Dados sanitizados por padrões não são anônimos por garantia.
- ZIP e exportações parciais não são campanha concluída; verificar cobertura e failed=0.
- Instalar/habilitar serviços do servidor não faz parte deste cliente portátil.

Todos os rótulos são provisórios. Revisão humana/calibração do acervo é uma etapa distinta.
