# API padrão — Homegrown AI Bridge

Endpoint público configurado no pacote fornecido pelo operador:

```text
https://homegrown-ai-bridge.lovable.app/api/public/v1
```

É endereço de serviço, não credencial. Pode ser substituído por --base-url ou HERMES_CLASSIFIER_API_BASE; nenhuma chave, conta de acesso ou configuração privada acompanha este repositório. Não acrescente o nome da rota à base.

## Credenciais por papel

CLIENT: consumidor → relay. AGENT: conector → polling/resultado do relay. Backend: conector → gateway local. São papéis distintos; nunca reaproveitar credenciais do Hermes/OpenAI. O cliente recusa prefixo lr_agent antes de rede/extração.

A chave CLIENT é lida de ambiente previamente provisionado, arquivo privado ou prompt local sem eco; nunca argv. Arquivo regular sem symlink, até 4 KiB; em POSIX, sem permissões para grupo/outros. Autenticação é o header `Authorization: Bearer <chave-CLIENT>`; o placeholder não deve ser copiado literalmente.

## Catálogo e seleção

GET <base>/models exige credencial. Exemplo sintético:

```json
{"data":[{"id":"clef-flash-9b-q4-k-m","task":"classification"}]}
```

A seleção prefere esse Flash se anunciado; senão, o único CLEF anunciado como classificação. Havendo ambiguidade, usar --model com ID literal válido. Catálogo não prova inferência nem disponibilidade de todos os modelos.

## Classificação

POST <base>/classifications recebe:

```json
{
  "model":"clef-flash-9b-q4-k-m",
  "state":"{\"tipo\":\"task\",\"contexto_auxiliar\":\"\",\"documento_para_classificar\":\"texto sintético\"}",
  "questions":{"dominio":{"type":"choice","instructions":"...","criteria":{"pessoal":"...","profissional":"...","misto":"...","compartilhado":"...","indeterminado":"..."}}}
}
```

Critérios reais/versionados: study.QUESTIONS. Resposta exige mesmo model e answers.dominio.choice/probabilities para os cinco rótulos; esquema, faixas e consistência são validados. Scores não são probabilidades calibradas. /chat/completions não substitui essa rota.

O cliente omite `keep_alive` por padrão, inclusive em lote. Uma opção explícita
`--keep-alive 0` envia zero; inteiros em segundos e `-1` são preservados, sem
garantia de que o backend atenda. A API Python aceita `RelayClient(..., keep_alive=0)`.

## Transporte e falhas

TLS padrão; sem redirects, proxy herdado, retry ou fallback. HTTP literal 127.0.0.1 só para testes. Payload máximo 1 MiB; resposta máxima 2 MiB. X-Relay-Timeout é limitado a 120s pelo cliente; o deadline de I/O padrão é 145s e --timeout o configura. DNS stdlib não cancelável impede promessa de limite absoluto incluindo resolução.

401/403: autenticação/permissão. 429: limite/ocupação. 504: o relay não entregou resultado no prazo; operador precisa verificar conector, fila e backend, sem inferir a causa só pelo código. Falhas permanecem no checkpoint e não são convertidas em classificação bem-sucedida. Este kit não instala o servidor nem resolve inicialização automática do PC dos modelos.
