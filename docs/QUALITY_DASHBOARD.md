# Relatório executivo de qualidade — uso e leitura

O HTML agora começa com **o que decidir**, seguido por indicadores com suas
bases, explicações e ações recomendadas. Os gráficos usam agrupamentos
**determinísticos**: não há uma segunda chamada de LLM para inventar a narrativa.

## Uma execução, um HTML

Exemplo público, sem chave, sem rede e somente dados sintéticos:

```sh
python3 -B examples/generate_quality_demo.py
```

Cria `examples/quality-dashboard.synthetic.html` **dentro deste repositório**.
O gerador usa o mesmo `quality-report` em uma pasta temporária privada, copia
somente o HTML sintético e descarta a pasta. Não acessa bancos ou perfis.
O arquivo traz o aviso **DADOS SINTÉTICOS**. Datas de 1970 na fixture são
segundos artificiais, não datas de operação de um cliente.

Para um arquivo de eventos autorizado, manter os resultados fora do checkout:

```sh
python3 -B cli.py quality-report \
  --input /caminho/autorizado/eventos.json \
  --tenant TENANT_EXPLICITO --work /pasta/privada/relatorio
```

São produzidos automaticamente, em `WORK/quality/`:

- `dashboard.html`: HTML autocontido, responsivo, com gráficos SVG e tabelas;
- `narrative.json`: conteúdo agregado e faixas que explicam as frases do HTML;
- `report.json`: métricas técnicas, cobertura, versão da narrativa e inferência;
- `tasks.jsonl`: projeção auditável, com proveniência, para revisão autorizada;
- manifestos/checkpoints: protegem retomada e identidade da campanha.

`quality-analyze` produz os mesmos artefatos e acrescenta rótulos provisórios
do modelo. `quality-report` é offline e informa explicitamente que não pediu
classificação. A disponibilidade de textos elegíveis não implica inferência
executada, falha do modelo ou cobertura perfeita.

O HTML não contém mensagens brutas nem identificadores de objetivos. Nomes de
fluxo, classe e versão aparecem nos recortes: isso **não é anonimização**.
Dados reais permanecem confidenciais, inclusive quando agregados. O HTML usa
CSS/SVG inline, não scripts, fontes, CDNs, analytics ou pedidos externos.

## O que o stakeholder encontra

1. **Prioridade de leitura:** se faltarem evidências, resolver a lacuna antes
   de concluir que um agente foi bom ou ruim.
2. **Oito indicadores:** resolução com evidência, primeira tentativa, correção
   humana, desconhecidos, mediana de tempo, tentativas adicionais, custo por
   resolução e tokens conhecidos. Cada um mostra base e limite interpretativo.
3. **Narrativa acionável:** observação → interpretação limitada → ação a
   investigar; não inventa a causa de uma taxa.
4. **Distribuições:** desfecho, elegibilidade, correções, 0/1/2+ novas tentativas,
   tempo até resolver, continuidade/abandono, falhas técnicas, tipos de
   intervenção e severidade. Rótulos de modelo ficam em gráficos separados.
5. **Recortes por fluxo, classe e versão**, incluindo metadados não informados;
   cada recorte tem denominadores próprios, sem ranking causal.
6. **Lacunas e metodologia:** limites da amostra, Wilson, cobertura e regras.
   As tabelas de cada gráfico podem ser expandidas; impressão tem CSS próprio.

Faixas v1: primeira tentativa `<50%`, `50% a <100%`, `100%`; correções `0%`,
`>0% a <30%`, `≥30%`. Os cortes são **descrições editoriais**, não SLAs, metas
validadas ou benchmarks de mercado. Menos de 20 grupos dispara aviso
exploratório, mas 20 ou mais **não** garante representatividade. Tempos usam
cortes de 1, 5 e 30 minutos, não metas de atendimento. `Não mensurável` não é 0.
A narrativa usa as frações não arredondadas; percentuais visuais têm uma casa.

## Smoke real pequeno, com gabarito anterior à inferência

```sh
env -u HERMES_CLASSIFIER_API_KEY python3 -B cli.py quality-smoke \
  --work /pasta/privada/smoke \
  --base-url http://127.0.0.1:8765/v1 --key-file "$ARQUIVO_CHAVE" \
  --model clef-flash-9b-q4-k-m --max-classifier-calls 7 --allow-relay
```

`ARQUIVO_CHAVE` deve apontar para uma chave já autorizada e protegida; o
exemplo não solicita nem imprime seu conteúdo. O endpoint precisa estar
ativo. O consentimento `--allow-relay` continua obrigatório, mesmo em loopback.
O comando é fixo: usa apenas `examples/quality-smoke.synthetic.json`, tenant
`synthetic-smoke` e gabarito `examples/quality-smoke.expected.json`; rejeita
`--input`/`--tenant` alternativos. São sete casos, uma mensagem por caso.

Além dos artefatos normais, gera `smoke-manifest.json` na raiz do WORK e
`quality/smoke-result.json` com hashes do protocolo, modelo, resultados por
controle, divergências, falhas e ausências. O próprio HTML incorpora o resumo.
A escrita dos resultados de validação e do HTML ocorre sob o lock da campanha.

- Exit **0**: todos os controles concordaram, sem falhas/ausências; ainda não
  homologa produção, calibração ou acurácia populacional.
- Exit **1**: divergências/falhas/ausências; **o HTML é gerado**, com o aviso.
- Exit **2**: erro de configuração, entrada, segurança ou pré-condição.

Retomar o mesmo `quality-smoke` com contrato intacto reutiliza checkpoints;
não refaz POSTs de inferência concluídos. Mudanças no arquivo de controles ou
na amostra exigem outra campanha. Não remover manifestos/checkpoints para
forçar repetição. O manifesto superior registra que a classificação começou:
perder a árvore interna e seu coordenador não autoriza reiniciar inferências.
Perder `smoke-manifest.json` em campanha já existente também bloqueia a
retomada, sem congelar um gabarito novo depois das respostas.

`quality-report` recupera os controles congelados e reavalia somente os
rótulos em cache, sem cliente, credencial ou chamadas à API. Preserva o
resultado exploratório e suas divergências no JSON, na narrativa e no HTML;
isso não é certificação. Rótulos em cache não são descritos como classificação
nunca executada. Para campanhas antigas, a recuperação exige correspondência
exata com os hashes do contrato original ainda preservado; se a prova faltar
ou divergir, o comando bloqueia em vez de apagar o resultado da validação.
O comando normal `quality-analyze` retornar 0 significa artefatos gerados,
não aprovação semântica do modelo.

## Resultado observado nesta entrega

O caminho real `CLI → gateway local → clef-flash-9b-q4-k-m → parser →
checkpoint → narrativa → HTML` foi exercitado: **7 decisões, 7 respostas
processáveis, zero falhas de classificação, 5/7 concordâncias** com o gabarito
sintético definido antes da primeira chamada. A retomada não alterou os
arquivos `results.jsonl` e não acrescentou novas inferências.

Duas divergências semânticas permaneceram visíveis, sem retunar o gabarito:

- `Não.` deveria levar à abstenção contextual; o modelo marcou correção.
- Uma promessa de enviar/testar o relatório foi rotulada como não resolução;
  o esperado era indeterminação: intenção sem resultado não comprova nem
  sucesso nem fracasso da entrega.

**Conclusão:** integração e geração automática funcionam; este classificador
**não está homologado para decidir sozinho**. As previsões não mudaram os
fatos: nenhuma dessas mensagens isoladas virou resolução comprovada. Isto não
é um benchmark, revisão humana cega, calibração ou avaliação em dados reais.
O HTML do smoke sintético real pode ser consultado em
`examples/quality-model-smoke.synthetic.html`; nenhum log bruto ou segredo
foi incluído nos exemplos públicos.
