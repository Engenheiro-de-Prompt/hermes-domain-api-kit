# Relatório executivo automático — contrato de entrega

## Objetivo aprovado

Permitir que um stakeholder entenda, em uma leitura, o que foi entregue, quanto retrabalho apareceu, quanto tempo levou, onde faltam dados e qual é a próxima ação defensável. Aprimorar o cliente existente e validar uma amostra sintética pequena com o Clef Flash real, sem ler históricos privados nem mudar serviços/modelos/configuração global.

## Descoberta e decisões

- O dashboard anterior de feedback (`feedback-all`/`feedback-report`) já possui séries semanais, média móvel ponderada e mediana. Será preservado; suas inferências de satisfação não virarão fatos sobre resolução.
- `quality-report`/`quality-analyze` já geram HTML automaticamente, mas sua apresentação é predominantemente técnica. O novo painel substitui apenas essa apresentação, com projeção agregada auditável.
- Separar cálculo, narrativa determinística versionada e renderização. Nenhum LLM escreve conclusões executivas. As mesmas entradas produzem a mesma narrativa/HTML; inferências reais não são prometidas como determinísticas.
- Abrir com decisão/limitação, depois KPIs, evidências visuais, recomendações condicionais e metodologia. Ausência nunca recebe zero nem cor de sucesso. Não criar nota geral de qualidade, meta, ROI, satisfação ou causalidade sem evidência.
- Faixas editoriais descritivas, não benchmarks de mercado: elegibilidade zero/parcial/completa; primeira tentativa abaixo da metade/metade ou mais/todas; correções nenhuma observada/alguma/ao menos 30% da base elegível. Amostras menores que 20 grupos são rotuladas exploratórias. Esse corte não é poder estatístico nem homologação.
- Denominadores e exclusões ficam junto dos números. Falha, desconhecido, não processado e abstenção do modelo são distintos. Score não é acurácia.
- Gráficos SVG estáticos autocontidos, com tabela textual equivalente; sem JavaScript, serviços externos ou instalação. Layout responsivo, contraste e impressão. Sem texto de mensagens, caminhos privados ou IDs no HTML.
- Dimensões explícitas de workflow/versão podem servir a segmentação descritiva; não comparar agentes causalmente nem inventar clusters semânticos. Faixas determinísticas de duração/tentativas servem ao agrupamento operacional.
- Artefatos operacionais permanecem em `--work` privado fora do checkout, preservando a proteção existente. Somente demonstrações exclusivamente sintéticas podem ser copiadas para `examples/` no repositório.

## Aceite verificável

1. Execução dos comandos existentes produz dashboard e narrativa agregada automaticamente, sem comando manual de renderização.
2. Stakeholder vê resolução observada, primeira tentativa elegível, retrabalho, duração e custo/cobertura, além de ação priorizada e limites.
3. Gráficos fecham suas bases ou explicitam sobreposição/exclusões; desconhecidos são visíveis. Dataset vazio, todo desconhecido e custo parcial não criam sucesso.
4. Regras e limites são testados em fronteiras; renderização repetida não muda bytes nem altera input.
5. HTML/SVG passam por parsers e inspeção visual desktop/celular. Sentinelas e payload HTML malicioso não vazam nem viram elementos ativos.
6. Amostra de controles positivos, negativos e ambíguos congelada antes da inferência real, com expectativas explícitas. Preservar respostas/erros/latência; executar pelo mesmo cliente/parser/classificador e geração HTML da produção.
7. Relatar acertos e erros reais da amostra sem chamá-la de homologação/estimativa populacional. Não mudar gabarito para acomodar modelo. Testar retomada sem nova inferência.
8. Regressão global e revisão independente do incremento; nenhum commit/push/deploy ou classificação de histórico real implícitos.
