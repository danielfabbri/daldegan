# DALDEGAN — Especificação Técnica

> Laboratório doméstico de investigação de intenção consciente sobre eventos aleatórios quânticos.

| Campo | Valor |
|---|---|
| Versão da spec | 0.1 (rascunho para desenvolvimento) |
| `PROTOCOL_VERSION` | `"1.0"` |
| `SOFTWARE_VERSION` inicial | `0.1.0` |
| Data | 2026-10-07 |

---

## 0. Princípio orientador

O Daldegan é um **instrumento de medição**, não uma máquina de confirmação. Toda decisão de projeto deve ser avaliada pela pergunta:

> "Isto permite que o usuário descubra que a hipótese dele estava errada?"

Se uma funcionalidade dificulta um resultado negativo, esconde dados, permite escolher a análise depois de ver os dados ou mistura fontes de aleatoriedade, ela está **fora do escopo** e deve ser rejeitada.

### 0.1 Pergunta de pesquisa

"Quando uma sequência de eventos quânticos é produzida e protegida contra observação humana, uma intenção consciente previamente definida ou realizada posteriormente está associada a uma diferença estatística consistente em relação ao esperado pelo acaso?"

### 0.2 Invariantes (nunca violar)

| ID | Invariante |
|---|---|
| INV-01 | Nenhum bit é alterado, descartado, reordenado, regenerado ou completado depois de recebido. |
| INV-02 | Uma sessão contém bits de **uma única fonte**. Nunca há fallback silencioso para PRNG. |
| INV-03 | Teste estatístico, hipótese alternativa (direção) e α são fixados no pré-registro, antes da geração, e são imutáveis. |
| INV-04 | Nenhuma informação derivada dos dados (contagens, proporções, sequência, gráficos, p-value, tamanho de arquivo variável, tempo de resposta dependente dos dados) é exposta antes do estado `REVEALED`. |
| INV-05 | Nenhuma sessão é excluída, ocultada ou sobrescrita pela interface. Sessões invalidadas continuam visíveis no histórico. |
| INV-06 | O número de participantes é apenas registrado; nunca entra no cálculo. |
| INV-07 | O texto da interface e dos relatórios é estatisticamente neutro; nunca afirma causalidade. |
| INV-08 | Sessões de teste (pseudoaleatórias) nunca entram em análises experimentais. |

---

## 1. Escopo

### 1.1 Dentro do escopo (primeira entrega — MVP)

1. Backend FastAPI local.
2. Frontend HTML/CSS/JS puro, responsivo.
3. Adapter QRNG (ANU) + fonte local apenas para teste.
4. Módulo 1 — intenção antes da geração.
5. Módulo 2 — intenção depois da geração (dados cegos).
6. Sessão Controle — mesmo fluxo do Módulo 2 com período neutro.
7. Armazenamento em CSV/JSON por sessão + índice SQLite.
8. SHA-256 de arquivos e manifesto.
9. `audit.log` com cadeia de hashes.
10. Máquina de estados com transições válidas explícitas.
11. Estatística (teste binomial exato, IC 95%, z-score).
12. Relatório HTML por sessão, exportações JSON/CSV.
13. Histórico de experimentos + análise acumulada (modo protocolo e modo exploratório).
14. Verificador externo independente (`scripts/verify_session.py`).
15. Suíte pytest (integridade, anti-adulteração, estatística).
16. README.

### 1.2 Fora do escopo do MVP (backlog)

- Análise exploratória por sessão com teste alternativo (seção 30 do briefing) — prevista em v0.2, ver §12.4.
- Ancoragem externa de hashes (ex.: OpenTimestamps, envio de hash a terceiros).
- Múltiplas fontes QRNG além da ANU.
- Autenticação / uso multiusuário em rede.
- Comparação estatística automática entre sessões de módulos diferentes (apenas exploratória, v0.2).

---

## 2. Arquitetura

### 2.1 Stack

| Camada | Tecnologia |
|---|---|
| Linguagem | Python 3.12+ |
| API | FastAPI + Uvicorn |
| Modelos | Pydantic v2 |
| HTTP cliente | httpx (async) |
| Estatística | scipy (`scipy.stats.binomtest`) |
| Índice | SQLite (`sqlite3` da stdlib) |
| Dados | CSV + JSON + JSONL em disco |
| Hash | `hashlib.sha256` |
| Testes | pytest, pytest-asyncio, httpx `ASGITransport` / `TestClient` |
| Frontend | HTML + CSS + JS puro (ES modules), servido pelo FastAPI como estático |

A aplicação roda **somente local**, vinculada a `127.0.0.1`. Não há banco externo.

### 2.2 Estrutura de diretórios

```
daldegan/
    backend/
        app/
            __init__.py
            main.py                 # cria app, monta rotas e estáticos
            config.py               # Settings (pydantic-settings / env)
            version.py              # SOFTWARE_VERSION, PROTOCOL_VERSION
            api/
                sessions.py
                history.py
                analysis.py
                system.py
            services/
                session_service.py  # orquestra fluxos dos módulos
                blind_view.py       # única forma de serializar sessão p/ UI
                report_service.py
                export_service.py
                cumulative_service.py
            models/
                enums.py            # Module, State, SourceType, ...
                session.py          # Pydantic: PreRegistration, Manifest, ...
                api.py              # DTOs de request/response
            statistics/
                binomial.py
            qrng/
                base.py             # RandomSource (ABC), erros
                anu.py              # QuantumRandomSource (ANU)
                local.py            # LocalRandomSource (somente teste)
                bits.py             # conversão bytes → bits documentada
            audit/
                audit_log.py        # append + verificação da cadeia
                hashing.py          # canonical JSON, sha256 de arquivos
            storage/
                session_store.py    # leitura/escrita de arquivos da sessão
                index_db.py         # SQLite (índice reconstruível)
            state_machine.py
        tests/
            conftest.py
            ...
    frontend/
        index.html
        css/
        js/
    data/
        sessions/                   # sessões experimentais (QRNG)
        sessions_test/              # sessões TEST_MODE_PSEUDORANDOM
        audit/                      # log global de criação de sessões
    scripts/
        verify_session.py
    SPEC.md
    TASKS.md
    README.md
    requirements.txt
    requirements-dev.txt
    .env.example
    .gitignore
    pyproject.toml                  # config do pytest (pythonpath, asyncio)
```

`storage/` e `state_machine.py` foram adicionados à estrutura do briefing para separar responsabilidades; isso não altera o contrato.

### 2.3 Fonte da verdade

**Os arquivos da sessão em disco são a fonte da verdade.** O SQLite é apenas um índice para listagem rápida e deve ser reconstruível a partir de `data/sessions*/` (`scripts/rebuild_index.py`, opcional). Em caso de divergência, os arquivos prevalecem e a divergência é reportada.

### 2.4 Regra de dependência

- `scripts/verify_session.py` **não importa nada de `backend/`**. Usa só stdlib + scipy. A lógica é duplicada de propósito, para que o verificador seja uma segunda implementação independente.
- O restante do sistema só conhece `RandomSource`; nenhum módulo fora de `qrng/` conhece URLs, parâmetros ou formatos da ANU.
- Toda resposta da API que descreve uma sessão passa por `blind_view.py`, que decide o que pode ser exposto conforme o estado.

---

## 3. Fonte de aleatoriedade

### 3.1 Interface

```python
class RandomSource(ABC):
    source_type: SourceType          # QUANTUM | PSEUDORANDOM_TEST
    source_name: str                 # ex.: "ANU QRNG"
    source_endpoint: str | None

    async def get_bits(self, count: int, on_progress=None) -> BitsResult: ...
```

`BitsResult` contém: `bits: list[int]`, `raw_blocks: list[RawBlock]` (cada bloco: timestamp da requisição, timestamp da resposta, parâmetros enviados, status HTTP, corpo bruto recebido), `bits_requested`, `bits_received`.

Em falha parcial, a fonte levanta `QRNGError` **carregando os blocos já recebidos**, para que a sessão os preserve.

### 3.2 QuantumRandomSource (ANU)

**Pré-requisito obrigatório (TASK T-001):** consultar a documentação oficial atual da ANU QRNG antes de implementar. Não inventar endpoint, parâmetros, limites ou gratuidade.

Verificado na T-001 (2026-10-07) — detalhes e citações em [docs/qrng-anu.md](docs/qrng-anu.md):

- Endpoint `https://api.quantumnumbers.anu.edu.au`, `GET`, header `x-api-key` (chave gratuita mediante cadastro; sem chave → 403).
- Parâmetros `length` (1–1024), `type` (`uint8` | `uint16` | `hex8` | `hex16`), `size` (1–10, só para hex).
- Plano gratuito: 100 requisições/mês, 1 requisição/s. Pago: US$ 0,005/requisição.
- A API antiga (`qrng.anu.edu.au/API/jsonI.php`) está limitada a 1 req/min e não é usada.
- Padrão do Daldegan: `type=uint8`, `length≤1024` → 8.192 bits por requisição, intervalo mínimo de 1,1 s entre requisições.

Configuração via variáveis de ambiente (nunca em código):

| Variável | Uso |
|---|---|
| `DALDEGAN_QRNG_API_KEY` | chave da API |
| `DALDEGAN_QRNG_ENDPOINT` | endpoint (default = documentado na T-001) |
| `DALDEGAN_QRNG_TIMEOUT_S` | timeout por requisição (default 30) |
| `DALDEGAN_QRNG_DATA_TYPE` | `uint8` (default) ou `hex16` (size 10; só após confirmação com chave real) |
| `DALDEGAN_DATA_DIR` | raiz de dados (default `./data`) |
| `DALDEGAN_SHOW_FULL_HASH` | `true`/`false` — exibe hash completo ou parcial na UI |

Comportamento:

- Requisições em sequência, sem paralelismo, para que a ordem dos blocos seja trivialmente a ordem de chegada.
- Cada bloco é persistido em `qrng_raw.jsonl` **assim que chega** (antes de converter em bits).
- Nenhum cache ou pré-busca fora da sessão.
- Sem retry automático que descarte respostas: se uma requisição falhar, a geração para (ver §3.5). Retry só é aceitável para falhas **sem corpo recebido** (ex.: erro de conexão antes da resposta), no máximo 2 vezes, e cada tentativa é registrada no audit log.

### 3.3 Conversão bytes → bits (documentada e fixa no protocolo 1.0)

- Pedir bytes (`uint8`, ou o tipo de maior rendimento confirmado na T-001 — se for hex, decodificar para bytes primeiro).
- Cada byte gera 8 bits, **MSB primeiro** (`(b >> 7) & 1, (b >> 6) & 1, …, b & 1`).
- Bytes são consumidos na ordem exata de recebimento, bloco a bloco.
- Pedir `ceil(N / 8)` bytes no total; usar os **primeiros N bits**. Os bits excedentes (< 8) não entram em `events.csv`, mas permanecem preservados em `qrng_raw.jsonl`.
- Essa transformação é bijetiva por byte e não introduz viés. Nenhum outro pós-processamento (debiasing, XOR, embaralhamento) é aplicado.
- A descrição textual da transformação é gravada no manifesto (`bit_extraction`).

### 3.4 LocalRandomSource

- Usa `secrets.token_bytes` + a mesma conversão de §3.3.
- `source_type = PSEUDORANDOM_TEST`.
- Só pode ser instanciada quando a sessão é criada com `test_mode = true`. A fábrica de fontes recebe o `source_type` declarado no pré-registro e **nunca** decide sozinha.
- Para testes automatizados, aceita um `seed` opcional (usa `random.Random(seed)`), registrado no manifesto.

### 3.5 Falha da fonte quântica

| Situação | Comportamento |
|---|---|
| Fonte indisponível ao criar/gerar | Erro claro na UI. Opções: **Cancelar** ou **Criar nova sessão em modo teste** (exige confirmação explícita). A sessão original não é convertida. |
| Falha no meio da geração | Sessão vai para `QRNG_ERROR` (terminal). Blocos recebidos são preservados exatamente. `events.csv` parcial é gravado com os bits recebidos, hasheado e marcado `partial: true`. Nunca é completado. |
| Servidor reinicia durante `GENERATING` | No startup, a sessão vai para `QRNG_ERROR` com motivo `interrupted`. |

"Modo teste" sempre cria **uma nova sessão** com ID `DALTEST-…`, em `data/sessions_test/`, com `source_type = PSEUDORANDOM_TEST` e marca `TEST_MODE_PSEUDORANDOM` visível em toda a UI e no relatório.

---

## 4. Modelo de dados

### 4.1 Identificador de sessão

`DAL-{AAAA}-{8 hex}` — ex.: `DAL-2026-3f9a1c07`, onde os 8 hex vêm de `uuid4().hex[:8]`. Em colisão (diretório já existe), gera outro; **nunca sobrescreve**. O UUID completo é guardado em `session_uuid`.

Decisão: o briefing mostra `DAL-2026-000001` (contador) e `DAL-2026-xxxxxxxx` (UUID). Adotou-se UUID porque não exige estado global e não pode colidir por concorrência.

Sessões de teste: `DALTEST-{AAAA}-{8 hex}`.

### 4.2 Arquivos por sessão

```
data/sessions/DAL-2026-3f9a1c07/
    preregistration.json    # imutável após PRE_REGISTERED
    manifest.json           # imutável após SEALED
    events.csv              # imutável após SEALED (somente leitura no SO também)
    qrng_raw.jsonl          # respostas brutas da fonte, append durante GENERATING
    audit.log               # JSONL append-only com cadeia de hashes
    analysis.json           # gerado na revelação; imutável depois
    report.html             # gerado a partir de analysis.json
```

### 4.3 Serialização canônica (base de todos os hashes)

- JSON: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`.
- Arquivos `.json` gravados em disco são exatamente esses bytes (sem indentação, sem newline final) — o hash do arquivo é igual ao hash do objeto canônico. Uma versão "bonita" pode ser produzida só para exibição/exportação.
- CSV: UTF-8 sem BOM, separador `,`, fim de linha `\n`, sem aspas.
- Timestamps: ISO 8601 UTC com microssegundos e sufixo `Z` (`2026-10-07T14:03:22.123456Z`).

### 4.4 `preregistration.json`

```json
{
  "protocol_version": "1.0",
  "software_version": "0.1.0",
  "session_id": "DAL-2026-3f9a1c07",
  "session_uuid": "…",
  "module": "MODULE_1 | MODULE_2 | CONTROL",
  "test_mode": false,
  "random_source": {"source_type": "QUANTUM", "source_name": "ANU QRNG", "source_endpoint": "…"},
  "planned_event_count": 10000,
  "planned_duration_seconds": 120,
  "participants_count": 3,
  "participant_labels": ["Participante 1", "Participante 2", "Participante 3"],
  "target_selection_method": "PARTICIPANT | SYSTEM_QUANTUM",
  "planned_target": 1,
  "statistical_test": "BINOMIAL_EXACT",
  "outcome_measure": "HITS",
  "null_hypothesis": "P(hit) = 0.5",
  "alternative_hypothesis": "TWO_SIDED | GREATER",
  "alpha": 0.05,
  "confidence_level": 0.95,
  "protocol_fingerprint": "sha256 de {module, test_mode, planned_event_count, planned_duration_seconds, target_selection_method, statistical_test, alternative_hypothesis, alpha, protocol_version}",
  "creation_timestamp": "…Z",
  "environment": {"python_version": "…", "os": "…", "git_commit": "… | null"}
}
```

Regras:

- **Módulo 1:** `planned_target` é obrigatório (0/1). Se `target_selection_method = SYSTEM_QUANTUM`, o alvo é sorteado com **1 bit** da fonte quântica *antes* de gravar o pré-registro; esse bit é registrado no audit log (`TARGET_RANDOMIZED`) e não faz parte de `events.csv`.
- **Módulo 2 e Controle:** `planned_target = null` obrigatoriamente.
- `preregistration_sha256` é calculado ao gravar, retornado à UI ("Seu protocolo foi registrado.") e registrado no audit log (`PREREGISTERED`). O arquivo pode ser baixado a qualquer momento.
- `participant_labels` é opcional; não exige nomes reais. A UI sugere "Participante N".

### 4.5 `events.csv`

```
event_id,sequence_number,bit,timestamp_utc
DAL-2026-3f9a1c07-000001,1,0,2026-10-07T14:05:01.000123Z
DAL-2026-3f9a1c07-000002,2,1,2026-10-07T14:05:01.000123Z
```

- `sequence_number` começa em 1 e é estritamente crescente sem lacunas.
- `event_id = {session_id}-{sequence_number:06d}` (com mais dígitos se N > 999999).
- `timestamp_utc` = momento em que o **bloco** QRNG que contém o bit foi recebido (bits do mesmo bloco compartilham o timestamp). Timestamp nunca é usado como fonte de aleatoriedade.
- `bit` ∈ {0, 1}. Internamente 0 = alvo A (AZUL), 1 = alvo B (VERMELHO); cores existem só no frontend.

### 4.6 `manifest.json` (gravado uma vez, no selamento)

```json
{
  "session_id": "…",
  "preregistration_sha256": "…",
  "source_type": "QUANTUM",
  "source_name": "ANU QRNG",
  "source_endpoint": "…",
  "request_timestamp": "…Z (primeira requisição)",
  "response_timestamp": "…Z (última resposta)",
  "number_of_bits_requested": 10000,
  "number_of_bits_received": 10000,
  "number_of_raw_bytes_received": 1250,
  "qrng_requests": 2,
  "bit_extraction": "uint8, MSB-first, 8 bits/byte, primeiros N bits, sem pós-processamento",
  "partial": false,
  "events_sha256": "…",
  "qrng_raw_sha256": "…",
  "event_count": 10000,
  "sealed_timestamp": "…Z"
}
```

`manifest_sha256` = SHA-256 dos bytes de `manifest.json`. Como não pode estar dentro do próprio arquivo, fica registrado no audit log (`DATA_SEALED.metadata.manifest_sha256`), no SQLite e no `analysis.json`.

Fatos posteriores ao selamento (alvo escolhido no Módulo 2, horários da intenção) **não** modificam o manifesto; ficam no `audit.log` (encadeado) e são consolidados em `analysis.json`.

### 4.7 `audit.log`

JSON Lines. Cada linha:

```json
{"seq":1,"timestamp":"…Z","session_id":"…","event":"SESSION_CREATED","metadata":{…},"hash_previous_log_entry":"000…0","hash_current_log_entry":"…"}
```

- `hash_current_log_entry = sha256(canonical_json(entrada sem o campo hash_current_log_entry))`.
- Primeira entrada: `hash_previous_log_entry = "0" * 64`.
- Abertura somente em modo append (`"a"`), com `flush` + `os.fsync` por linha.
- Nenhum endpoint permite apagar ou editar o log.

Eventos padronizados:

```
SESSION_CREATED, TARGET_RANDOMIZED, PREREGISTERED,
TARGET_SELECTED,
INTENTION_STARTED, INTENTION_COMPLETED,
GENERATION_STARTED, QRNG_BLOCK_RECEIVED, QRNG_RETRY, QRNG_ERROR, GENERATION_COMPLETED,
DATA_SEALED,
REVEAL_REQUESTED, HASH_VERIFIED, AUDIT_CHAIN_VERIFIED, INTEGRITY_FAILED,
RESULT_REVEALED, ANALYSIS_COMPLETED, SESSION_COMPLETED,
SESSION_INVALIDATED, SESSION_CANCELLED
```

Log global (`data/audit/sessions.log`, mesmo formato encadeado): uma linha por sessão criada. Serve para detectar remoção de diretório de sessão — o histórico compara o log global com os diretórios existentes e sinaliza sessões ausentes.

**Limitação documentada:** um adversário com acesso de escrita ao disco pode reescrever a cadeia inteira. A cadeia detecta adulterações parciais e acidentais; para garantia mais forte, o usuário deve anotar/compartilhar o `preregistration_sha256` e o `events_sha256` fora da máquina (recomendado na UI). Ancoragem externa automática é backlog.

### 4.8 `analysis.json`

```json
{
  "session_id": "…",
  "module": "…",
  "test_mode": false,
  "preregistration_sha256": "…",
  "manifest_sha256": "…",
  "events_sha256": "…",
  "audit_head_hash": "hash da última entrada antes de ANALYSIS_COMPLETED",
  "target": 1,
  "target_selection_method": "…",
  "target_selected_timestamp": "…Z",
  "intention_started_at": "…Z",
  "intention_completed_at": "…Z",
  "participants_count": 3,
  "n": 10000,
  "zeros": 4972,
  "ones": 5028,
  "hits": 5028,
  "observed_proportion": 0.5028,
  "expected_proportion": 0.5,
  "absolute_deviation": 0.0028,
  "deviation_pp": 0.28,
  "z_score": 0.56,
  "statistical_test": "BINOMIAL_EXACT",
  "alternative_hypothesis": "TWO_SIDED",
  "alpha": 0.05,
  "p_value": 0.5755,
  "ci_method": "CLOPPER_PEARSON",
  "ci_95": [0.4930, 0.5126],
  "significant": false,
  "result_statement": "Não foi detectado desvio estatisticamente significativo.",
  "proportion_of_ones": 0.5028,
  "analyzed_timestamp": "…Z",
  "software_version": "0.1.0",
  "protocol_version": "1.0"
}
```

Valores de ponto flutuante são arredondados para 12 casas antes da serialização, para que o verificador externo reproduza o JSON byte a byte.

### 4.9 SQLite (`data/daldegan.db`)

Tabela `sessions`: `session_id PK, module, test_mode, state, created_at, planned_event_count, participants_count, target, target_selection_method, protocol_fingerprint, preregistration_sha256, events_sha256, manifest_sha256, intention_ends_at, observed_proportion, p_value, integrity_status, invalid_reason, dir_path`.

`observed_proportion` e `p_value` só são preenchidos a partir de `REVEALED`.

---

## 5. Máquina de estados

### 5.1 Estados

```
CREATED, PRE_REGISTERED, GENERATING, SEALED, TARGET_SELECTED,
INTENTION_RUNNING, REVEAL_PENDING, REVEALED, ANALYZED, COMPLETED,
INVALIDATED, QRNG_ERROR, CANCELLED
```

`QRNG_ERROR` e `CANCELLED` foram adicionados à lista do briefing: `QRNG_ERROR` é exigido pela seção 25; `CANCELLED` permite abandonar uma sessão antes da geração sem apagá-la.

Terminais: `COMPLETED`, `INVALIDATED`, `QRNG_ERROR`, `CANCELLED`.

### 5.2 Transições por módulo

**Módulo 1 — intenção antes da geração**

```
CREATED → PRE_REGISTERED          (alvo já definido no pré-registro)
PRE_REGISTERED → TARGET_SELECTED  (confirmação do alvo; TARGET_SELECTED no log)
TARGET_SELECTED → INTENTION_RUNNING
INTENTION_RUNNING → GENERATING    (somente se agora ≥ intention_ends_at)
GENERATING → SEALED | QRNG_ERROR
SEALED → REVEAL_PENDING
REVEAL_PENDING → REVEALED | INVALIDATED
REVEALED → ANALYZED → COMPLETED
```

**Módulo 2 e Controle — dados antes da intenção**

```
CREATED → PRE_REGISTERED          (planned_target = null)
PRE_REGISTERED → GENERATING
GENERATING → SEALED | QRNG_ERROR
SEALED → TARGET_SELECTED          (M2: participante ou sorteio quântico;
                                   Controle: alvo-placebo sorteado, ver §6.3)
TARGET_SELECTED → INTENTION_RUNNING
INTENTION_RUNNING → REVEAL_PENDING  (somente se agora ≥ intention_ends_at)
REVEAL_PENDING → REVEALED | INVALIDATED
REVEALED → ANALYZED → COMPLETED
```

**Comuns:** `CREATED | PRE_REGISTERED | TARGET_SELECTED (M1)` → `CANCELLED`. Qualquer estado não terminal → `INVALIDATED` quando uma verificação de integridade falhar.

### 5.3 Regras

- Transições ficam numa tabela explícita `{(module, from_state): {to_states}}`. Qualquer outra lança `IllegalTransition` (HTTP 409).
- Toda transição gera uma entrada no audit log e atualiza o SQLite **depois** de gravar o log.
- Tempos são controlados **pelo servidor**: `intention_started_at` e `intention_ends_at = started + planned_duration_seconds` são gravados ao iniciar; o cliente só exibe o cronômetro. Concluir a intenção antes do tempo retorna 409. A intenção sobrevive a reinício do servidor (é só timestamp).
- A camada de armazenamento consulta o estado antes de qualquer escrita: escrever `events.csv`/`manifest.json`/`qrng_raw.jsonl` fora de `GENERATING` lança `SealedSessionError`. Após o selamento, os arquivos também recebem `chmod` somente leitura (defesa adicional, não a principal).

---

## 6. Fluxos dos módulos

### 6.1 Módulo 1 — Intenção antes da geração

Testa: "Uma intenção previamente definida está associada a uma alteração na distribuição dos eventos quânticos subsequentes?"

1. Usuário configura: eventos, participantes, duração, método de seleção do alvo, direção do teste (default bilateral).
2. Se `PARTICIPANT`: escolhe 0/AZUL ou 1/VERMELHO. Se `SYSTEM_QUANTUM`: sistema sorteia 1 bit quântico.
3. Pré-registro gravado e hasheado → "Seu protocolo foi registrado." + hash + botão baixar `preregistration.json`.
4. Usuário inicia intenção → cronômetro, alvo, participantes. Nenhum dado existe ainda.
5. Ao fim do tempo → `INTENTION_COMPLETED` → geração quântica com barra de progresso (progresso = bits recebidos / solicitados, que não revela conteúdo).
6. Selamento (hashes, manifesto) → "Dados coletados." → `REVEAL_PENDING`.
7. **REVELAR RESULTADO** → verificação (§8) → resultado.

### 6.2 Módulo 2 — Intenção depois da geração

Rótulo fixo na UI: **"Dados gerados antes da intenção e mantidos cegos até a conclusão da intenção."**

1. Configuração (sem alvo). Pré-registro com `planned_target = null`.
2. "Gerando e selando os dados quânticos." + progresso.
3. Selamento → "Dados gerados e selados." + SHA-256 de `events.csv` (completo ou parcial conforme `DALDEGAN_SHOW_FULL_HASH`) e recomendação de anotá-lo fora da máquina.
4. "Agora escolha o alvo da intenção." (ou sorteio quântico, com 1 bit de **requisição separada**, registrado em `TARGET_RANDOMIZED`; esse bit não é um evento).
5. `TARGET_SELECTED` com `target_selected_timestamp`.
6. Intenção: "Durante os próximos N minutos, concentrem sua atenção no alvo escolhido." Cronômetro, alvo, participantes.
7. Fim → `REVEAL_PENDING` → "Período concluído." → **REVELAR RESULTADO** → verificação → resultado.

### 6.3 Controle — período neutro

Mesmo fluxo temporal do Módulo 2, com as diferenças:

- A UI pede atividade neutra ("Permaneçam em atividade neutra; não há alvo a ser focado.").
- **Decisão:** para permitir comparar a mesma medida (`HITS`) com o Módulo 2, o sistema sorteia um **alvo-placebo** com 1 bit quântico logo após o selamento. Esse alvo **não é mostrado** durante o período neutro e só aparece no resultado. Registrado como `target_selection_method = SYSTEM_QUANTUM_SHAM`.
- O resultado também mostra a proporção de uns (P(1)), que é a medida natural sem alvo.

### 6.4 Comparação entre sessões

Nenhuma comparação automática entre Módulo 2 e Controle no MVP. Qualquer comparação futura será marcada **ANÁLISE EXPLORATÓRIA**.

---

## 7. Estatística

### 7.1 Medida e hipóteses

- Medida primária (`HITS`): número de eventos com `bit == target`.
- H0: P(hit) = 0,5.
- H1 (default, pré-registrado): P(hit) ≠ 0,5 — `TWO_SIDED`.
- H1 direcional opcional: P(hit) > 0,5 — `GREATER`. Escolhida apenas no pré-registro.
- α default 0,05. No MVP o α é fixo em 0,05 (não editável), para eliminar mais um grau de liberdade; o campo existe no pré-registro para versões futuras.
- Teste: binomial exato (`scipy.stats.binomtest(k=hits, n=n, p=0.5, alternative=…)`).

### 7.2 Métricas

| Métrica | Fórmula |
|---|---|
| `observed_proportion` | hits / n |
| `expected_proportion` | 0,5 |
| `absolute_deviation` | observed − 0,5 (com sinal) |
| `deviation_pp` | 100 × absolute_deviation |
| `z_score` | (hits − n/2) / √(n/4) — informativo; a decisão usa o p-value exato |
| `ci_95` | Clopper-Pearson exato (`binomtest(...).proportion_ci(0.95, method="exact")`), sempre bilateral |
| `significant` | p_value < α |

### 7.3 Linguagem do resultado (lista fechada)

- `significant = false` → "Não foi detectado desvio estatisticamente significativo."
- `significant = true` → "Foi detectado um desvio estatisticamente significativo."

Sempre acompanhado de:

> "O p-value indica quão incomum seria um resultado pelo menos tão extremo quanto este se apenas o acaso estivesse atuando (H0 verdadeira). Ele **não** é a probabilidade de a hipótese ser verdadeira, e um resultado isolado não estabelece causa."

Um teste automatizado varre templates e textos do frontend/relatório procurando frases proibidas ("a intenção funcionou", "a consciência alterou", "a oração causou", "comprova", "prova que").

### 7.4 Tamanho da amostra

Opções: 100, 500, 1.000, 5.000, 10.000 (default), 50.000, 100.000 ou customizado (mín. 10, máx. 1.000.000; o máximo efetivo pode ser limitado pela cota QRNG verificada na T-001).

Texto fixo: "Quanto maior o número de eventos, maior a capacidade de detectar pequenos desvios estatísticos, mas um único experimento pequeno não é suficiente para estabelecer uma conclusão robusta."

A UI mostra, como informação pré-experimento, o desvio mínimo detectável aproximado para o N escolhido (≈ 1,96 × 0,5/√N), calculado sem nenhum dado.

### 7.5 Análise acumulada

Dois modos:

**A) Por protocolo (confirmatório)**
- Agrupa por `protocol_fingerprint` (parâmetros fixados antes da geração).
- Inclui **todas** as sessões não-teste com aquele fingerprint em estado `COMPLETED`.
- Lista também, sem incluir no cálculo mas sem esconder, as sessões `INVALIDATED`, `QRNG_ERROR`, `CANCELLED` e as ainda em andamento, com contagem de cada.
- Calcula `total_events, total_zeros, total_ones, total_hits, combined_proportion, binomial_test, ci_95`, usando o teste e a direção do próprio protocolo.
- A tela lista todos os fingerprints existentes, para que nenhum protocolo "ruim" fique escondido.

**B) Seleção manual (exploratória)**
- Usuário escolhe sessões. Cabeçalho obrigatório: **"Esta análise é exploratória e está sujeita a viés de seleção."** Teste sempre bilateral.
- Mesmas métricas.

Sessões de teste nunca aparecem em nenhum dos dois modos (existe uma aba separada só para elas).

---

## 8. Revelação e integridade

### 8.1 Cegamento (antes de `REVEALED`)

A API e a UI podem expor **apenas**: `session_id`, módulo, estado, etapa, participantes, duração, alvo (exceto alvo-placebo do Controle), tempo restante, progresso da coleta (bits recebidos/solicitados), hashes (`preregistration_sha256`, `events_sha256`, `manifest_sha256`), texto "Os dados estão selados."

Não podem expor: contagens, proporções, médias, sequência, gráficos, p-value, desvio, conteúdo de `events.csv`/`qrng_raw.jsonl`/`analysis.json`, nem tamanho de arquivo (embora o tamanho de `events.csv` seja determinístico pelo formato fixo, ele não é exibido).

Implementação:
- `blind_view.serialize(session)` é a **única** função que monta respostas sobre sessões; usa uma allowlist por estado.
- Endpoints de resultado/exportação/eventos retornam **423 Locked** antes de `REVEALED`.
- Os arquivos de dados não são servidos como estáticos.
- **Limitação documentada:** o cegamento é procedimental. O usuário local pode abrir `events.csv` no disco. O README orienta a não fazê-lo e explica que isso compromete a sessão.

### 8.2 Procedimento de revelação

Ao clicar **REVELAR RESULTADO** (só em `REVEAL_PENDING`):

1. `REVEAL_REQUESTED` no log.
2. Verificar existência e formato de todos os arquivos.
3. Recalcular SHA-256 de `preregistration.json`, `manifest.json`, `events.csv`, `qrng_raw.jsonl` e comparar com os valores registrados (manifesto, audit log, SQLite).
4. Validar `events.csv`: cabeçalho, contagem = `event_count` = `planned_event_count`, bits ∈ {0,1}, sequência 1..N contínua, `event_id` coerente.
5. Validar que os bits de `events.csv` são exatamente os derivados de `qrng_raw.jsonl` pela regra de §3.3.
6. Validar o pré-registro: campos imutáveis iguais aos do SQLite (alvo, participantes, duração, teste, α, direção).
7. Verificar a cadeia do `audit.log` e a ordem temporal dos eventos (ex.: no M2, `DATA_SEALED` < `TARGET_SELECTED` < `INTENTION_STARTED`; `INTENTION_COMPLETED` ≥ início + duração).
8. Tudo OK → `HASH_VERIFIED`, `AUDIT_CHAIN_VERIFIED`, `RESULT_REVEALED` → análise → `analysis.json` → `ANALYSIS_COMPLETED` → relatório → `COMPLETED`.
9. Qualquer falha → `INTEGRITY_FAILED` + `SESSION_INVALIDATED` com motivo → UI mostra **"SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada."** Nenhuma estatística é exibida como válida.

(Se a própria cadeia do audit log estiver corrompida, a entrada `SESSION_INVALIDATED` é registrada no SQLite e no log global, já que não é possível estender uma cadeia inválida.)

---

## 9. API HTTP

Prefixo `/api`. Respostas JSON. Erros: 400 (validação), 404, 409 (transição ilegal / cedo demais), 423 (dados cegos), 503 (fonte QRNG indisponível).

| Método | Rota | Descrição | Estados permitidos |
|---|---|---|---|
| GET | `/system/info` | versões, fonte configurada, se API key existe (sem revelá-la) | — |
| POST | `/sessions` | cria + pré-registra. Body: `module, event_count, participants_count, participant_labels?, duration_seconds, target_selection_method, target? (M1), alternative_hypothesis, test_mode` | — |
| GET | `/sessions/{id}` | visão cega/segura via `blind_view` | todos |
| GET | `/sessions/{id}/preregistration` | download `preregistration.json` | ≥ PRE_REGISTERED |
| POST | `/sessions/{id}/generate` | inicia geração (background task) | M2/C: PRE_REGISTERED · M1: após intenção concluída |
| POST | `/sessions/{id}/target` | `{target}` ou `{method:"SYSTEM_QUANTUM"}` | M2: SEALED |
| POST | `/sessions/{id}/intention/start` | inicia período | TARGET_SELECTED |
| POST | `/sessions/{id}/intention/complete` | conclui (409 se antes do tempo) | INTENTION_RUNNING |
| POST | `/sessions/{id}/cancel` | cancela | CREATED, PRE_REGISTERED, TARGET_SELECTED (M1) |
| POST | `/sessions/{id}/reveal` | verifica e revela | REVEAL_PENDING |
| GET | `/sessions/{id}/result` | `analysis.json` + validade | ≥ REVEALED (423 antes) |
| GET | `/sessions/{id}/verify` | roda verificação de integridade (não altera estado após COMPLETED; apenas reporta) | SEALED+ (sem estatísticas antes de REVEALED) |
| GET | `/sessions/{id}/report.html` | relatório | COMPLETED / INVALIDATED |
| GET | `/sessions/{id}/export.json` | pré-registro + manifesto + análise + audit log | COMPLETED / INVALIDATED |
| GET | `/sessions/{id}/events.csv` | eventos | ≥ REVEALED |
| GET | `/history` | lista; proporção/p-value `null` para sessões não reveladas | — |
| GET | `/history.csv` | exporta histórico | — |
| GET | `/analysis/protocols` | lista de fingerprints com contagens por estado | — |
| POST | `/analysis/cumulative` | `{mode:"PROTOCOL", fingerprint}` ou `{mode:"MANUAL", session_ids}` | — |

Não existe endpoint de DELETE, nem de edição de sessão, alvo, estatística ou log.

Para geração: `POST /generate` responde 202; a UI faz polling em `GET /sessions/{id}` (progresso e estado).

---

## 10. Frontend

### 10.1 Princípios

- SPA leve com hash-routing (`#/`, `#/novo`, `#/sessao/{id}`, `#/historico`, `#/verificar`, `#/docs`, `#/analise`).
- Linguagem simples durante o experimento; termos técnicos só na tela de resultado/documentação.
- Mobile-first, funciona de 360px a desktop.
- Nenhum dado de resultado é guardado no `localStorage`.
- Faixa **MODO TESTE — dados pseudoaleatórios** fixa no topo em sessões `DALTEST-`.

### 10.2 Telas

**Início** — "DALDEGAN" / "Laboratório experimental de aleatoriedade e intenção" / [NOVO EXPERIMENTO] [HISTÓRICO] [VERIFICAR SESSÃO] [DOCUMENTAÇÃO]. Link secundário para "Análise de múltiplas sessões".

**Novo experimento** — rádio Módulo 1 / Módulo 2 / Controle (com descrição de uma linha); eventos (presets + custom) com texto de §7.4; participantes ("Quantas pessoas participarão da intenção?") + rótulos opcionais; duração (presets 1, 2, 5, 10 min + custom 10 s–60 min); método do alvo (participante / sorteado pelo sistema — não aparece no Controle); "Opções avançadas": hipótese bilateral (default) ou direcional. Texto "Você está prestes a registrar uma hipótese experimental." [CONTINUAR].

**Indicador de etapas** em todos os fluxos: "Etapa 1 de 4 — Preparando experimento…", "Etapa 2 de 4 — Dados quânticos gerados.", "Etapa 3 de 4 — Período de intenção.", "Etapa 4 de 4 — Revelação." (No Módulo 1 a ordem das etapas 2 e 3 é invertida, mantendo a numeração por posição.)

**Módulo 1** — "Escolha seu alvo." [🔵 0 — AZUL] [🔴 1 — VERMELHO] → "Alvo registrado." → "Agora começa o período de intenção." ALVO / PARTICIPANTES / TEMPO RESTANTE → "Intenção concluída." "Agora estamos coletando os eventos quânticos." barra → "Dados coletados." [REVELAR RESULTADO].

**Módulo 2** — "Gerando e selando os dados quânticos." barra → "Dados gerados e selados." SHA-256 → "Agora escolha o alvo da intenção." → "Durante os próximos N minutos, concentrem sua atenção no alvo escolhido." ALVO / PARTICIPANTES / TEMPO → "Período concluído." [REVELAR RESULTADO].

**Controle** — igual ao Módulo 2 sem escolha de alvo, com texto de atividade neutra.

**Durante cegamento** — somente "Os dados estão selados." e "Tempo restante: mm:ss".

**Resultado** — Eventos, Zeros, Uns, Alvo, Proporção do alvo, Esperado, Desvio (p.p. com sinal), p-value, IC 95%, frase de §7.3, explicação do p-value, gráfico de barras 0/1 (HTML/CSS, sem biblioteca) com linha de 50% e IC. "Experimento concluído." Botões: relatório HTML, exportar JSON, exportar CSV.

**Invalidada** — "SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada." + motivo técnico + nenhuma estatística.

**Histórico** — tabela: session_id, data, módulo, eventos, participantes, alvo, proporção, p-value, integridade (OK / INVALIDADA / ERRO QRNG / pendente). Inclui todas as sessões; sessões ausentes do disco (detectadas pelo log global) aparecem como "AUSENTE". Botão exportar CSV. Aba separada para sessões de teste.

**Verificar sessão** — seleciona sessão → roda `/verify` → mostra checagens item a item; mostra o comando do verificador externo para copiar.

**Documentação** — versão HTML resumida do README (o que testa / o que não testa / p-value / viés de seleção / pré-registro).

**Análise de múltiplas sessões** — modos A e B de §7.5.

### 10.3 Fluxo de falha da fonte

Modal: "Não foi possível obter números da fonte quântica. Nenhum dado pseudoaleatório foi usado." [CANCELAR] [CRIAR SESSÃO EM MODO TESTE]. O segundo botão exige confirmação ("Esta sessão não terá valor experimental e não entrará nas análises.").

---

## 11. Relatório HTML

Arquivo autocontido (CSS inline, sem JS), seções:

1. Identificação da sessão
2. Protocolo (pré-registro completo + hash)
3. Fonte QRNG (tipo, nome, endpoint, nº de requisições, transformação de bits)
4. Número de eventos
5. Participantes
6. Alvo e método de seleção
7. Cronologia (do audit log)
8. Integridade (cada verificação)
9. Resultado
10. Estatística (teste, direção, α, p, IC, z, explicação do p-value)
11. Limitações (cegamento procedimental, amostra única, múltiplas comparações, ausência de causalidade, fonte externa)
12. Hashes
13. Versão do software / protocolo / ambiente

Rodapé fixo: **"Este relatório descreve os dados observados. Ele não estabelece uma explicação causal para qualquer desvio observado."**

---

## 12. Verificador externo

### 12.1 Uso

```
python scripts/verify_session.py data/sessions/DAL-2026-3f9a1c07
```

Opcional: `--json` para saída legível por máquina. Exit code 0 = OK, 1 = falhou, 2 = erro de uso.

### 12.2 Verificações

1. Ler `preregistration.json`, `manifest.json`, `events.csv`, `qrng_raw.jsonl`, `audit.log`, `analysis.json` (se existir).
2. Recalcular SHA-256 de cada arquivo.
3. Comparar com manifesto e audit log (`PREREGISTERED`, `DATA_SEALED`).
4. Validar número de eventos (= manifesto = pré-registro).
5. Validar bits ∈ {0,1}.
6. Validar sequência contínua e `event_id`.
7. Revalidar bits a partir de `qrng_raw.jsonl`.
8. Validar a cadeia do `audit.log` e a ordem temporal dos eventos por módulo.
9. Recalcular estatísticas com scipy e comparar com `analysis.json` (tolerância 1e-9 para floats).
10. Imprimir cada checagem e, ao final, `INTEGRIDADE: OK` ou `INTEGRIDADE: FALHOU`.

### 12.3 Independência

Nenhum import de `backend`. Usa stdlib + scipy. Teste `test_external_verifier_matches_application` executa o script por `subprocess` e compara com o resultado da aplicação.

### 12.4 Análise exploratória por sessão (v0.2)

Será um arquivo separado `exploratory/<timestamp>_<teste>.json`, marcado `EXPLORATORY ANALYSIS`, sem alterar `analysis.json`, registrado no audit log. Fora do MVP.

---

## 13. Reprodutibilidade

Gravado no pré-registro e no relatório: `software_version`, `protocol_version`, `git_commit` (via `git rev-parse HEAD`, `null` se indisponível), versão do Python, `platform.platform()`, versões de scipy/fastapi, fonte QRNG, endpoint, timestamps UTC.

Regra: qualquer mudança em formato de arquivo, regra de hash, conversão de bits, teste estatístico ou fluxo de módulo incrementa `PROTOCOL_VERSION`. Fingerprints incluem a versão, então sessões de protocolos diferentes nunca são somadas no modo A.

---

## 14. Segurança

- Bind em `127.0.0.1` por padrão; README avisa contra expor na rede.
- API key só por variável de ambiente; nunca logada, nunca retornada pela API, nunca gravada nos arquivos da sessão.
- `.gitignore` inclui `.env`, `data/`, `.venv/`.
- Validação estrita de `session_id` (regex `^DAL(TEST)?-\d{4}-[0-9a-f]{8}$`) antes de montar caminhos — evita path traversal.
- Sem `DELETE`, sem edição.

---

## 15. Testes

### 15.1 Integridade (nomes do briefing, obrigatórios)

```
test_hash_changes_when_event_changes
test_hash_changes_when_manifest_changes
test_cannot_reveal_before_intention
test_cannot_read_results_before_reveal
test_cannot_modify_sealed_events
test_event_count_matches_manifest
test_events_are_binary
test_event_sequence_is_monotonic
test_audit_chain_is_valid
test_external_verifier_matches_application
test_invalid_session_is_rejected
```

### 15.2 Anti-adulteração (cada um deve resultar em INVALIDATED na revelação **e** `INTEGRIDADE: FALHOU` no verificador)

alterar um bit · apagar um evento · adicionar um evento · alterar o alvo · alterar nº de participantes · alterar duração · alterar estatística (`analysis.json`) · alterar manifesto · alterar `audit.log` (editar, remover linha, reordenar) · alterar `qrng_raw.jsonl` · revelar antes do tempo (409) · acessar resultados/eventos/export durante cegamento (423) · transições ilegais (409) · tentar criar sessão quântica e receber PRNG (impossível).

### 15.3 Estatística

- 10.000 bits balanceados (5.000/5.000) → proporção 0,5, p = 1,0, não significativo.
- 5.500 zeros / 4.500 uns → detecta desvio (p ≪ 0,05) em ambos os sentidos de alvo.
- Direcional: alvo com proporção < 0,5 e `GREATER` → não significativo.
- Extremos: n pequeno (10), todos 0, todos 1, n = 1.000.000.
- IC Clopper-Pearson contra valores de referência conhecidos.
- z-score contra cálculo manual.

### 15.4 Fonte

- `QuantumRandomSource` com transporte HTTP mockado (`httpx.MockTransport`): conversão bytes→bits, múltiplos blocos na ordem, falha parcial preserva blocos, API key ausente → erro claro, sem fallback.
- Fábrica: sessão não-teste nunca recebe `LocalRandomSource`.
- Teste de integração real com a ANU marcado `@pytest.mark.qrng_live` e pulado por padrão (consome cota).

### 15.5 Linguagem

Varredura de frases proibidas em `frontend/` e templates de relatório.

### 15.6 Fluxos ponta a ponta

M1, M2 e Controle completos via `TestClient` com `LocalRandomSource` em modo teste e relógio injetável (para não esperar minutos reais).

---

## 16. Decisões registradas

| ID | Decisão | Motivo |
|---|---|---|
| D-01 | Arquivos em disco são a fonte da verdade; SQLite é índice | auditabilidade sem ferramentas |
| D-02 | ID `DAL-AAAA-8hex` (UUID) | sem estado global, sem colisão |
| D-03 | JSON canônico compacto em disco | hash do arquivo = hash do objeto |
| D-04 | Bits MSB-first de `uint8` | transformação simples, documentável, sem viés |
| D-05 | Medida primária = HITS (bit == alvo) | unifica M1/M2/Controle e análise acumulada |
| D-06 | Bilateral por padrão; direcional só no pré-registro | evita escolha posterior |
| D-07 | α fixo em 0,05 no MVP | menos graus de liberdade |
| D-08 | IC Clopper-Pearson exato | conservador, padrão para binomial |
| D-09 | Controle usa alvo-placebo quântico oculto | mesma medida que M2 |
| D-10 | Alvo sorteado usa requisição QRNG separada, fora de `events.csv` | não contamina a amostra |
| D-11 | Estados extras `QRNG_ERROR`, `CANCELLED` | exigidos pelo briefing / abandono sem apagar |
| D-12 | Manifesto imutável após selamento; fatos posteriores no audit log | `manifest_sha256` estável |
| D-13 | Tempo controlado pelo servidor; relógio injetável nos testes | impede revelar cedo; testes rápidos |
| D-14 | Verificador duplica a lógica, sem importar o backend | independência real |
| D-15 | Modo A agrupa por `protocol_fingerprint` e inclui todas as sessões COMPLETED | pré-especificado, sem seleção posterior |
| D-16 | Log global de sessões | detecta remoção de diretórios |
| D-17 | Cegamento é procedimental (arquivo local legível) — documentado | limitação inerente a app local |
| D-18 | "Código de auditoria" (hash da última entrada do audit log) exibido na UI + `--anchor` no verificador | detectar reescrita completa da cadeia sem serviço externo |

---

## 17. Ajustes feitos durante a implementação (v0.1.0)

- **Módulo 1:** o alvo já está no pré-registro, então a sessão passa automaticamente de `PRE_REGISTERED` para `TARGET_SELECTED` logo após o pré-registro. Ao concluir a intenção, `INTENTION_COMPLETED` é registrado no audit log e a sessão entra em `GENERATING`. Depois do selamento, ela vai para `REVEAL_PENDING` (evento `AWAITING_REVEAL`).
- **Módulo 2:** o método de seleção do alvo (participante ou sorteio quântico) é fixado no pré-registro. `POST /sessions/{id}/target` recebe apenas `{target}` quando o método é PARTICIPANT, ou `{}` quando é SYSTEM_QUANTUM. Se o sorteio falhar, a sessão continua em `SEALED` e o erro é registrado (`QRNG_ERROR` no log, sem mudança de estado), para que a operação possa ser repetida sem perder os dados selados.
- **Controle:** o sorteio do alvo-placebo acontece logo após o selamento. Se falhar, a sessão continua em `SEALED`, e `POST /target` tenta o sorteio de novo.
- **Estados:** `SEALED → QRNG_ERROR` foi removido da tabela do Módulo 2 e do Controle (ver os dois itens acima). `CREATED → QRNG_ERROR` existe apenas no Módulo 1 (falha no sorteio do alvo antes do pré-registro).
- **Eventos derivados do bruto:** `events.csv` é sempre construído a partir do `qrng_raw.jsonl` persistido, nunca da memória. Isso garante que eventos e respostas brutas coincidam.
- **API extra:** `GET /api/planning?event_count=N` devolve o desvio mínimo detectável e o número de requisições à fonte, sem usar nenhum dado. As respostas de sessão incluem `audit_code` (D-18) e `session_path`.
- **Verificador externo:** aceita `--anchor HASH` (pode repetir) para conferir códigos de auditoria anotados fora da máquina.
- **Módulos de código:** histórico, exportações e análise acumulada ficaram em `services/history_service.py`; a verificação da aplicação está em `services/integrity.py`; as rotas estão em `api/routes.py`.

## 18. Critérios de aceitação

O MVP está pronto quando:

- [ ] `uvicorn backend.app.main:app --reload` inicia e serve `http://127.0.0.1:8000`.
- [ ] Consegue obter bits reais da ANU QRNG com a chave configurada.
- [ ] Gera sessões dos três tipos e completa M1, M2 e Controle pela interface.
- [ ] Nenhuma informação dos dados aparece antes da revelação (verificado por teste).
- [ ] `events.csv` preservado e hash validado na revelação.
- [ ] Alteração de qualquer arquivo invalida a sessão.
- [ ] Relatório HTML gerado.
- [ ] `python scripts/verify_session.py <dir>` retorna `INTEGRIDADE: OK` em sessão íntegra e `FALHOU` em sessão adulterada.
- [ ] `pytest` passa integralmente (exceto `qrng_live`, pulado por padrão).
- [ ] README cobre todos os tópicos da seção 28 do briefing.
