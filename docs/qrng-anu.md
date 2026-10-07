# ANU Quantum Numbers (AQN) — verificação da API (T-001)

Data de acesso: 2026-10-07.

## Fontes consultadas

- https://quantumnumbers.anu.edu.au/documentation — página "API Documentation" (SPA; texto lido diretamente do bundle JS oficial `chunk-2d0e91c4.36279d84.js`, servido pelo próprio site).
- https://quantumnumbers.anu.edu.au/pricing — planos (bundle `chunk-2d22922a.ed04ca33.js`).
- FAQ do site (bundle `chunk-48b03468.b08fc4fe.js`).
- Teste direto, sem chave, do endpoint novo e do antigo (resultados abaixo).

## Endpoint e autenticação (texto oficial)

- `API_URL=https://api.quantumnumbers.anu.edu.au`
- Exemplo oficial:
  `curl -X GET -H "x-api-key:${API_KEY}" "${API_URL}?length=[array length]&type=[data type]&size=[block size]"`
- "You will need an API key which you can get for free by signing up."
- Sem chave, a API responde `HTTP 403 {"message":"Forbidden"}` (testado em 2026-10-07).

## Parâmetros (texto oficial)

> The AQN JSON API supports three parameters.
> - **Data type**: must be 'uint8' (returns integers between 0-255), 'uint16' (returns integers between 0-65535), 'hex8' (returns hexadecimal characters between 00-ff) or 'hex16' (returns hexadecimal characters between 0000-ffff).
> - **Array length**: the length of the array to return. Must be between 1-1024.
> - **Block size**: only needed for 'hex8' and 'hex16' data types. Sets the length of each block. Must be between 1-10.

Exemplos oficiais: `?length=10&type=uint8`, `?length=5&type=uint16`, `?length=10&type=hex8&size=2`.

## Planos (texto oficial)

| Plano | Preço | Limites |
|---|---|---|
| Trial (gratuito) | US$ 0 | "100 requests per month", "1 request per second" — "100 requests per calendar month" |
| Paid (AWS Marketplace) | US$ 0,005/requisição | "Unlimited requests", "100 requests per second" |

## API antiga

`https://qrng.anu.edu.au/API/jsonI.php` ainda responde (2026-10-07) com
`{"type":"uint8","length":4,"data":[58,0,75,143],"success":true}`, mas está limitada:
"The QRNG API is limited to 1 requests per minute. For more requests, please visit https://quantumnumbers.anu.edu.au".
**Não é usada** pelo Daldegan.

## Não documentado oficialmente

- O formato exato do JSON de resposta da API nova não aparece na página de documentação. A API antiga e catálogos de terceiros indicam `{"type","length","data":[...],"success":true}`.
  Decisão: o adapter exige `success == true` e `data` como lista com exatamente `length` itens válidos para o `type`; qualquer outra coisa é erro (`QRNGError`). O corpo bruto é sempre preservado em `qrng_raw.jsonl`.
- Ordem de bytes dentro de `uint16`: não documentada. Por isso o Daldegan **não** usa `uint16`.

## Decisões derivadas (protocolo 1.0)

- Tipo padrão: `uint8`, `length` até 1024 → **8.192 bits por requisição**.
  - 10.000 eventos = 2 requisições; 100.000 eventos = 13 requisições.
  - Com o plano gratuito (100 req/mês): ~819.200 bits/mês, menos 1 requisição por sorteio quântico de alvo.
- Tipo alternativo configurável (`DALDEGAN_QRNG_DATA_TYPE=hex16`, `size=10`): cada item é uma string hex de 10 × 4 = 40 caracteres = 20 bytes; até 1024 itens → 163.840 bits por requisição. Conversão: `bytes.fromhex(item)` na ordem da string (esquerda→direita), itens na ordem do array. Só deve ser habilitado depois de confirmar com uma chave real que o formato da resposta corresponde a isso (ver T-111).
- Intervalo mínimo de 1,1 s entre requisições (respeita "1 request per second" do plano gratuito).
- Máximo de eventos por sessão: 1.000.000 (122 requisições em `uint8`, acima da cota gratuita mensal; a UI mostra quantas requisições a sessão vai consumir antes de criar).
