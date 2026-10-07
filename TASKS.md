# DALDEGAN — Plano de tarefas

Referência: [SPEC.md](SPEC.md). Cada tarefa cita as seções da spec que implementa.

**Status em 2026-10-07:** T-001 a T-110 concluídas; 118 testes passando (`pytest`). Falta T-111, que exige uma chave da ANU.

Legenda: `[ ]` a fazer · `[~]` em andamento · `[x]` concluída · **Dep.** = depende de.

Regra geral: uma tarefa só é marcada `[x]` quando seus testes passam. Nenhuma tarefa pode violar os invariantes INV-01..08 (SPEC §0.2).

---

## Fase 0 — Preparação

- [x] **T-001 — Verificar a API oficial da ANU QRNG** (SPEC §3.2)
  - Consultar a documentação oficial atual: endpoint, autenticação, parâmetros, tipos, limite por requisição, cota gratuita, formato da resposta, códigos de erro.
  - Registrar em `docs/qrng-anu.md` com URLs e data de acesso.
  - Atualizar SPEC §3.2 e §7.4 (máximo de eventos pela cota).
  - Se a API não for mais gratuita/acessível: parar e decidir fonte alternativa com o usuário antes de T-030.
  - **Aceite:** documento criado; nenhum pressuposto "a confirmar" restante na §3.2.

- [x] **T-002 — Estrutura do projeto** (SPEC §2.2)
  - Criar diretórios, `__init__.py`, `requirements.txt` (fastapi, uvicorn, pydantic, pydantic-settings, httpx, scipy), `requirements-dev.txt` (pytest, pytest-asyncio), `pyproject.toml` (pythonpath, markers `qrng_live`), `.gitignore`, `.env.example`.
  - `git init` + primeiro commit.
  - **Aceite:** `pip install -r requirements-dev.txt` e `pytest` (zero testes) rodam.

- [x] **T-003 — Versão e configuração** (SPEC §3.2, §13)
  - `version.py` com `SOFTWARE_VERSION = "0.1.0"`, `PROTOCOL_VERSION = "1.0"`.
  - `config.py` com Settings lidas de env (`DALDEGAN_*`).
  - Função `collect_environment()` (python, OS, git commit ou null, versões de libs).
  - **Dep.** T-002.

---

## Fase 1 — Núcleo de domínio

- [x] **T-010 — Enums e modelos Pydantic** (SPEC §4.4–4.8)
  - `Module`, `State`, `SourceType`, `TargetSelectionMethod`, `Alternative`, `StatisticalTest`.
  - `PreRegistration`, `Manifest`, `Event`, `AuditEntry`, `Analysis`, DTOs da API.
  - Validações: `planned_target` obrigatório no M1 e `null` no M2/Controle; limites de eventos, duração e participantes; regex de `session_id`.
  - **Testes:** validações aceitam/rejeitam os casos corretos.
  - **Dep.** T-003.

- [x] **T-011 — Hash e JSON canônico** (SPEC §4.3)
  - `canonical_json(obj) -> bytes`, `sha256_bytes`, `sha256_file`, arredondamento de floats (12 casas), formatação de timestamp UTC.
  - **Testes:** `test_hash_changes_when_event_changes`, `test_hash_changes_when_manifest_changes`, estabilidade (mesma entrada → mesmo hash, independente da ordem das chaves).
  - **Dep.** T-002.

- [x] **T-012 — Máquina de estados** (SPEC §5)
  - Tabela explícita de transições por módulo; `IllegalTransition`.
  - Relógio injetável (`Clock` protocolo) para controle de tempo da intenção.
  - **Testes:** todas as transições válidas passam; uma amostra exaustiva de inválidas (produto cartesiano estados × estados) falha; terminais não saem.
  - **Dep.** T-010.

---

## Fase 2 — Armazenamento e auditoria

- [x] **T-020 — Audit log encadeado** (SPEC §4.7)
  - `AuditLog.append(event, metadata)` com fsync; `verify_chain(path) -> Result`.
  - Log global `data/audit/sessions.log`.
  - **Testes:** `test_audit_chain_is_valid`; editar linha, remover linha, reordenar linhas, inserir linha → cadeia inválida.
  - **Dep.** T-011.

- [x] **T-021 — SessionStore (arquivos da sessão)** (SPEC §4.1, §4.2, §5.3)
  - Criação do diretório sem sobrescrever (erro se existir), geração de ID com retry em colisão.
  - Escrita de `preregistration.json`, `qrng_raw.jsonl` (append por bloco), `events.csv`, `manifest.json`, `analysis.json`.
  - Guarda de estado: escrita fora do estado permitido → `SealedSessionError`; `chmod` read-only após selamento.
  - Separação `data/sessions/` × `data/sessions_test/`.
  - **Testes:** `test_cannot_modify_sealed_events`; não sobrescreve sessão existente; path traversal rejeitado.
  - **Dep.** T-012, T-020.

- [x] **T-022 — Índice SQLite** (SPEC §4.9)
  - Schema, upsert por transição, consultas do histórico e por fingerprint.
  - Estatísticas só gravadas a partir de `REVEALED`.
  - **Testes:** índice nunca contém proporção/p-value de sessão não revelada.
  - **Dep.** T-010.

---

## Fase 3 — Fontes de aleatoriedade

- [x] **T-030 — Abstração e conversão de bits** (SPEC §3.1, §3.3)
  - `RandomSource` (ABC), `BitsResult`, `RawBlock`, `QRNGError` (carregando blocos parciais).
  - `qrng/bits.py`: bytes → bits MSB-first, corte nos primeiros N.
  - **Testes:** conversões conhecidas (`0b10110000` → `1,0,1,1,0,0,0,0`), ordem entre blocos, corte de excedente.
  - **Dep.** T-001, T-010.

- [x] **T-031 — QuantumRandomSource (ANU)** (SPEC §3.2)
  - Implementar exatamente conforme `docs/qrng-anu.md`. API key via env; nunca logada.
  - Requisições sequenciais, callback de progresso e de bloco recebido (para persistir imediatamente).
  - Retry somente sem corpo recebido (máx. 2), sinalizado ao chamador.
  - **Testes (httpx.MockTransport):** sucesso em 1 e N blocos; falha no meio preserva blocos; key ausente → erro; resposta malformada → erro; teste real `@pytest.mark.qrng_live` pulado por padrão.
  - **Dep.** T-030.

- [x] **T-032 — LocalRandomSource e fábrica** (SPEC §3.4)
  - `secrets` por padrão; `seed` opcional para testes, registrado.
  - `make_source(source_type)` — sessão não-teste só recebe a fonte quântica.
  - **Testes:** fábrica nunca retorna local para sessão experimental; ausência de fallback quando a quântica falha.
  - **Dep.** T-030.

---

## Fase 4 — Estatística

- [x] **T-040 — Binomial e métricas** (SPEC §7.1–7.3)
  - `analyze(bits, target, alternative, alpha)` → hits, proporções, desvio, z, p (scipy `binomtest`), IC Clopper-Pearson, `significant`, `result_statement` (lista fechada).
  - Função de desvio mínimo detectável (§7.4), independente de dados.
  - **Testes:** 5.000/5.000; 5.500/4.500 com alvo 0 e alvo 1; direcional no sentido oposto; n = 10; todos 0; todos 1; n = 1.000.000; IC e z contra valores de referência.
  - **Dep.** T-010.

- [x] **T-041 — Análise acumulada** (SPEC §7.5)
  - Modo PROTOCOL (por fingerprint, todas as COMPLETED, lista as demais por estado) e modo MANUAL (flag exploratória, sempre bilateral).
  - Exclusão de sessões de teste.
  - **Testes:** sessão desfavorável nunca é excluída do modo A; sessões de teste nunca entram; flag exploratória presente no modo B; protocolos diferentes não se misturam.
  - **Dep.** T-040, T-022.

---

## Fase 5 — Serviço de sessões (fluxos)

- [x] **T-050 — Criação e pré-registro** (SPEC §4.4, §6)
  - Cria sessão, sorteio quântico de alvo no M1 quando aplicável (antes do pré-registro), grava `preregistration.json`, calcula hash e fingerprint, audit `SESSION_CREATED`/`TARGET_RANDOMIZED`/`PREREGISTERED`, log global.
  - **Dep.** T-021, T-022, T-032.

- [x] **T-051 — Geração e selamento** (SPEC §3.5, §4.5, §4.6)
  - Background task: `GENERATING`, persistência de cada bloco, conversão, `events.csv`, `manifest.json`, hashes, `DATA_SEALED` com `manifest_sha256`.
  - Falha → `QRNG_ERROR` com dados parciais preservados e marcados `partial`.
  - Startup: sessões presas em `GENERATING` → `QRNG_ERROR (interrupted)`.
  - Progresso consultável (bits recebidos/solicitados).
  - **Dep.** T-050, T-031.

- [x] **T-052 — Alvo pós-selamento e intenção** (SPEC §6.2, §6.3, §5.3)
  - M2: alvo do participante ou sorteado (requisição separada). Controle: alvo-placebo oculto `SYSTEM_QUANTUM_SHAM`.
  - `intention/start` grava `intention_ends_at`; `intention/complete` só após o tempo (relógio do servidor).
  - M1: após intenção concluída → dispara geração.
  - **Testes:** `test_cannot_reveal_before_intention`; completar intenção cedo → 409; alvo-placebo não aparece antes da revelação.
  - **Dep.** T-051.

- [x] **T-053 — Verificação de integridade da aplicação** (SPEC §8.2)
  - Serviço `integrity.verify(session_dir)` com todas as checagens de §8.2 (hashes, formato, contagem, bits, sequência, bits vs. raw, pré-registro vs. índice, cadeia e ordem temporal).
  - **Testes:** `test_event_count_matches_manifest`, `test_events_are_binary`, `test_event_sequence_is_monotonic`.
  - **Dep.** T-020, T-021.

- [x] **T-054 — Revelação e análise** (SPEC §8.2, §4.8)
  - `reveal`: verificação → `REVEALED` → `analysis.json` → `ANALYZED` → relatório → `COMPLETED`; falha → `INVALIDATED` com motivo.
  - Tratamento de cadeia corrompida (registro no SQLite + log global).
  - **Testes:** `test_invalid_session_is_rejected`.
  - **Dep.** T-052, T-053, T-040.

- [x] **T-055 — Blind view** (SPEC §8.1)
  - `blind_view.serialize(session)` com allowlist por estado; única via de serialização para a API.
  - **Testes:** para cada estado anterior a `REVEALED`, a resposta não contém nenhuma chave/valor proibido (contagens, proporções, p, bits, alvo-placebo).
  - **Dep.** T-010.

---

## Fase 6 — API

- [x] **T-060 — App FastAPI e rotas** (SPEC §9)
  - `main.py`: app, montagem de `frontend/` como estático, bind padrão 127.0.0.1, hook de startup (T-051).
  - Rotas de `sessions`, `history`, `analysis`, `system`, com mapeamento de erros (400/404/409/423/503).
  - Sem rotas de DELETE/edição.
  - **Testes:** `test_cannot_read_results_before_reveal` (result, events.csv, export, report → 423); transições ilegais → 409; `/system/info` não expõe a API key.
  - **Dep.** T-054, T-055, T-041.

- [x] **T-061 — Exportações e histórico** (SPEC §9, §10.2)
  - `export.json`, `events.csv` (pós-revelação), `history` e `history.csv` com nulos para não reveladas, detecção de sessões ausentes via log global.
  - **Dep.** T-060.

---

## Fase 7 — Relatório

- [x] **T-070 — Relatório HTML** (SPEC §11)
  - Template autocontido com as 13 seções, rodapé obrigatório, versão para sessão invalidada (sem estatísticas).
  - Gerado a partir de `analysis.json` + audit log.
  - **Testes:** contém rodapé, hashes e todas as seções; relatório de sessão invalidada não contém p-value.
  - **Dep.** T-054.

---

## Fase 8 — Verificador externo

- [x] **T-080 — `scripts/verify_session.py`** (SPEC §12)
  - Implementação independente (stdlib + scipy, sem importar `backend`).
  - Saída item a item + `INTEGRIDADE: OK|FALHOU`; `--json`; exit codes.
  - **Testes:** `test_external_verifier_matches_application` (via subprocess); teste estático que garante ausência de `import backend` no script.
  - **Dep.** T-054 (para ter sessões reais a verificar).

---

## Fase 9 — Frontend

- [x] **T-090 — Base do frontend** (SPEC §10.1)
  - `index.html`, CSS mobile-first, roteador por hash, cliente de API, componente de etapas, faixa de MODO TESTE.
  - **Dep.** T-060.

- [x] **T-091 — Início e Novo experimento** (SPEC §10.2)
  - Seleção de módulo, presets, textos fixos, opções avançadas (direção), desvio mínimo detectável, exibição do hash do pré-registro + download.
  - **Dep.** T-090.

- [x] **T-092 — Fluxo Módulo 1** (SPEC §6.1, §10.2)
  - **Dep.** T-091.

- [x] **T-093 — Fluxo Módulo 2 e Controle** (SPEC §6.2, §6.3, §10.2)
  - Tela de selamento com hash; tela cega ("Os dados estão selados." + tempo restante).
  - **Dep.** T-091.

- [x] **T-094 — Resultado e invalidação** (SPEC §7.3, §10.2)
  - Métricas, frase fixa, explicação do p-value, gráfico de barras CSS com linha 50% e IC, botões de exportação.
  - **Dep.** T-092, T-093.

- [x] **T-095 — Falha da fonte / modo teste** (SPEC §3.5, §10.3)
  - Modal com cancelar / criar nova sessão de teste com dupla confirmação.
  - **Dep.** T-091.

- [x] **T-096 — Histórico, Verificar, Análise múltipla, Documentação** (SPEC §7.5, §10.2)
  - **Dep.** T-061, T-041.

---

## Fase 10 — Testes de segurança e ponta a ponta

- [x] **T-100 — Suíte anti-adulteração** (SPEC §15.2)
  - Fixture que produz sessão M2 completa em `REVEAL_PENDING` (fonte local com seed + relógio falso).
  - Parametrizar: alterar bit, apagar evento, adicionar evento, alterar alvo, participantes, duração, `analysis.json`, manifesto, `qrng_raw.jsonl`, audit log (editar/remover/reordenar).
  - Para cada caso: revelação → `INVALIDATED` **e** verificador externo → `FALHOU`.
  - **Dep.** T-054, T-080.

- [x] **T-101 — Testes ponta a ponta dos três fluxos** (SPEC §15.6)
  - M1, M2, Controle via `TestClient`, incluindo sorteio de alvo pelo sistema.
  - **Dep.** T-060.

- [x] **T-102 — Teste de linguagem proibida** (SPEC §7.3, §15.5)
  - Varre `frontend/` e templates de relatório.
  - **Dep.** T-070, T-094.

- [x] **T-103 — Rodar `pytest` completo e corrigir todas as falhas**
  - **Dep.** todas as anteriores.

---

## Fase 11 — Documentação e aceite

- [x] **T-110 — README.md** (briefing §28, §39)
  - O que é; o que testa; o que NÃO testa.
  - Diferença entre observação, medição, interação física, consciência, intenção, aleatoriedade, correlação e causalidade.
  - Mecânica quântica não estabelece que a consciência seja necessária ao colapso; experimento não demonstra que oração funciona; significância isolada ≠ causalidade.
  - Múltiplas comparações, p-hacking, viés de seleção, importância do pré-registro, por que o Módulo 2 é conceitualmente interessante, "Um resultado negativo também é um resultado válido."
  - Limitações (cegamento procedimental, cadeia de hash reescrevível localmente, dependência da fonte externa).
  - Comandos: venv, ativação (Windows/Linux/macOS), `pip install`, `uvicorn backend.app.main:app --reload`, `http://127.0.0.1:8000`, `pytest`, `python scripts/verify_session.py <SESSION_PATH>`, configuração da API key.
  - **Dep.** T-103.

- [ ] **T-111 — Checklist de aceitação manual** (SPEC §18)
  - Executar com a ANU real: uma sessão de cada módulo, um verificador OK, uma adulteração manual detectada, um relatório gerado.
  - Registrar o resultado (IDs das sessões e saída do verificador) em `docs/acceptance-0.1.0.md`.
  - **Dep.** T-110, chave da API configurada.
  - Também confirmar o formato real da resposta da API nova (o adapter exige `success: true` e `data` com `length` itens; ver docs/qrng-anu.md).

---

## Backlog (após o MVP)

- [ ] B-01 — Análise exploratória por sessão marcada `EXPLORATORY ANALYSIS` (SPEC §12.4).
- [ ] B-02 — Comparação exploratória Módulo 2 × Controle.
- [ ] B-03 — Ancoragem externa automática de hashes (OpenTimestamps ou similar). A âncora manual (`--anchor`) já existe.
- [ ] B-04 — Fontes QRNG adicionais via o mesmo adapter.
- [ ] B-05 — α configurável no pré-registro.
- [ ] B-06 — `scripts/rebuild_index.py` para reconstruir o SQLite a partir dos arquivos.

---

## Ordem sugerida de execução

```
T-001 ─┐
T-002 → T-003 → T-010 → T-011 → T-012 → T-020 → T-021 → T-022
                  │                                        │
                  ├→ T-030 → T-031, T-032 ─────────────────┤
                  ├→ T-040 → T-041 ────────────────────────┤
                  └→ T-055                                 │
                                                           ▼
            T-050 → T-051 → T-052 → T-053 → T-054 → T-060 → T-061
                                              │        │
                                              ├→ T-070 ├→ T-090 … T-096
                                              └→ T-080 │
                                                       ▼
                                   T-100, T-101, T-102 → T-103 → T-110 → T-111
```

T-001 é bloqueante apenas para T-031; o restante pode avançar com a `LocalRandomSource` em testes.
