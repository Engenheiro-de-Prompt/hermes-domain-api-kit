# Evidências e limites de validação

## Distribuição pública

A suíte offline contém 40 testes stdlib de extrator, transporte HTTP em loopback, CLI, classificação/checkpoints/exportação e segurança. A revisão pré-publicação executa a árvore staged em ambiente limpo, sem chave real, modelos ou instalação de pacotes. O workflow `tests` executa os mesmos testes nos sistemas indicados; o status do commit no GitHub é a evidência remota, não uma promessa deste texto.

Os testes verificam requisições HTTP reais **sintéticas**, ausência de redirects e proxies herdados, erros sem eco, limites, corpo gotejado, extração SQLite/query_only, preservação de textos, cobertura bloqueante e retomada sem replay.

## Inferência real anterior à publicação

O mecanismo de origem foi exercitado via relay público autorizado, com conteúdo exclusivamente sintético: cinco exemplos tiveram os rótulos esperados, e seis itens de um Hermes sintético percorreram extração → API → datasets sem falhas. Uma cópia extraída com HOME vazio também completou esse circuito. Os comprovantes privados não são publicados porque podem conter metadados operacionais.

A preparação pública não altera o corpo de transporte, o extrator ou o classificador validado. Esses ensaios ocorreram no host de desenvolvimento acessando uma URL pública; **não** comprovam origem em outra máquina física, qualquer API nova, qualidade geral, execução com acervo real ou ausência universal de dados sensíveis.

A API de cada consumidor precisa passar pelo `verify` próprio. O CI não usa inferência real nem segredos. Rótulos são provisórios; scores não são probabilidades calibradas. A precisão no seu acervo exige revisão humana/calibração separadas.
