import { api, ApiError } from "./api.js";

const app = document.getElementById("app");

// ------------------------------------------------------------------ util

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

const fmtInt = (n) => Number(n).toLocaleString("pt-BR");
const fmtPct = (x, d = 2) => `${(100 * x).toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d })}%`;
const fmtP = (p) => (p < 0.0001 ? p.toExponential(2) : p.toLocaleString("pt-BR", { maximumFractionDigits: 4 }));
const fmtTime = (s) => {
  const t = Math.max(0, Math.ceil(s));
  return `${String(Math.floor(t / 60)).padStart(2, "0")}:${String(t % 60).padStart(2, "0")}`;
};

const TARGETS = {
  0: { label: "AZUL", cls: "blue", emoji: "🔵" },
  1: { label: "VERMELHO", cls: "red", emoji: "🔴" },
};
const MODULES = {
  MODULE_1: { title: "Módulo 1 — Intenção antes da geração", short: "Módulo 1" },
  MODULE_2: { title: "Módulo 2 — Intenção depois da geração", short: "Módulo 2" },
  CONTROL: { title: "Controle — período neutro", short: "Controle" },
};
const M2_LABEL = "Dados gerados antes da intenção e mantidos cegos até a conclusão da intenção.";
const INVALID_MSG = "SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada.";

let timers = [];
function clearTimers() {
  timers.forEach((t) => clearInterval(t));
  timers = [];
}

function render(...nodes) {
  clearTimers();
  app.replaceChildren(...nodes);
  window.scrollTo(0, 0);
}

function errorBox(err) {
  return h("p", { class: "error" }, err instanceof ApiError ? err.message : String(err));
}

function targetBadge(t) {
  if (t === null || t === undefined) return "—";
  const info = TARGETS[t];
  return h("span", { class: `target-label ${info.cls}` }, `${info.emoji} ${t} — ${info.label}`);
}

function hashLine(label, value) {
  return value ? [h("dt", {}, label), h("dd", { class: "hash" }, value)] : [];
}

// ------------------------------------------------------------------ início

function viewHome() {
  render(
    h("section", { class: "hero" },
      h("h1", {}, "DALDEGAN"),
      h("p", { class: "muted" }, "Laboratório experimental de aleatoriedade e intenção"),
    ),
    h("div", { class: "menu" },
      h("a", { class: "btn", href: "#/novo" }, "NOVO EXPERIMENTO"),
      h("a", { class: "btn secondary", href: "#/historico" }, "HISTÓRICO"),
      h("a", { class: "btn secondary", href: "#/verificar" }, "VERIFICAR SESSÃO"),
      h("a", { class: "btn secondary", href: "#/docs" }, "DOCUMENTAÇÃO"),
      h("a", { class: "btn secondary", href: "#/analise" }, "ANÁLISE DE MÚLTIPLAS SESSÕES"),
    ),
    h("p", { class: "muted small center" },
      "Um instrumento para testar uma hipótese — inclusive para descobrir que ela está errada. ",
      "Um resultado negativo também é um resultado válido."),
  );
}

// ---------------------------------------------------------- novo experimento

const EVENT_PRESETS = [100, 500, 1000, 5000, 10000, 50000, 100000];
const DURATION_PRESETS = [1, 2, 5, 10];

async function viewNew(prefill = null) {
  const info = await api.info().catch(() => null);
  const form = {
    module: prefill?.module || "MODULE_2",
    event_count: prefill?.event_count || 10000,
    participants_count: prefill?.participants_count || 1,
    duration_seconds: prefill?.duration_seconds || 120,
    target_selection_method: prefill?.target_selection_method || "PARTICIPANT",
    alternative_hypothesis: prefill?.alternative_hypothesis || "TWO_SIDED",
    test_mode: prefill?.test_mode || false,
  };

  const planningEl = h("p", { class: "muted small" });
  async function updatePlanning() {
    try {
      const p = await api.planning(form.event_count, form.test_mode);
      const req = p.qrng_requests === null ? "" :
        ` Esta sessão fará ${p.qrng_requests} requisição(ões) à fonte quântica.`;
      planningEl.textContent =
        `Com ${fmtInt(form.event_count)} eventos, desvios menores que cerca de ` +
        `${p.minimum_detectable_deviation_pp.toLocaleString("pt-BR", { maximumFractionDigits: 2 })} ponto percentual ` +
        `dificilmente serão detectados.${req}`;
    } catch { planningEl.textContent = ""; }
  }

  const eventsInput = h("input", { type: "number", min: 10, max: 1000000, value: form.event_count,
    oninput: (e) => { form.event_count = Number(e.target.value); updatePlanning(); } });
  const durationInput = h("input", { type: "number", min: 10, max: 3600, value: form.duration_seconds,
    oninput: (e) => { form.duration_seconds = Number(e.target.value); } });
  const participantsInput = h("input", { type: "number", min: 1, max: 1000, value: form.participants_count,
    oninput: (e) => { form.participants_count = Number(e.target.value); } });

  const methodBlock = h("div", {},
    h("label", {}, "Quem escolhe o alvo?"),
    h("div", { class: "radio-list" },
      radio("method", "PARTICIPANT", form.target_selection_method, "Alvo escolhido pelo participante", null,
        (v) => (form.target_selection_method = v)),
      radio("method", "SYSTEM_QUANTUM", form.target_selection_method, "Alvo sorteado pelo sistema",
        "Usa um bit da própria fonte quântica. Evita preferência sistemática por um alvo.",
        (v) => (form.target_selection_method = v)),
    ),
  );
  const syncMethod = () => { methodBlock.style.display = form.module === "CONTROL" ? "none" : ""; };

  function radio(name, value, current, title, desc, onchange) {
    return h("label", {},
      h("input", { type: "radio", name, value, checked: value === current,
        onchange: () => { onchange(value); syncMethod(); } }),
      h("span", {}, h("strong", {}, title), desc ? h("span", { class: "muted small" }, desc) : null));
  }

  const errorEl = h("div");
  const noKey = info && !info.quantum_source.api_key_configured;

  render(
    h("h1", {}, "Novo experimento"),
    h("p", {}, "Você está prestes a registrar uma hipótese experimental."),
    noKey ? h("p", { class: "banner test" },
      "A fonte quântica não está configurada (DALDEGAN_QRNG_API_KEY). Sessões experimentais não poderão ser criadas; ",
      "apenas sessões em modo teste, sem valor experimental.") : null,
    h("div", { class: "card" },
      h("label", {}, "Tipo de experimento"),
      h("div", { class: "radio-list" },
        radio("module", "MODULE_1", form.module, MODULES.MODULE_1.title,
          "Você escolhe o alvo e faz a intenção. Só depois os dados quânticos são gerados.", (v) => (form.module = v)),
        radio("module", "MODULE_2", form.module, MODULES.MODULE_2.title,
          `${M2_LABEL}`, (v) => (form.module = v)),
        radio("module", "CONTROL", form.module, MODULES.CONTROL.title,
          "Mesmo fluxo do Módulo 2, mas sem intenção: um período neutro.", (v) => (form.module = v)),
      ),

      h("label", {}, "Número de eventos"),
      h("div", { class: "chips" }, EVENT_PRESETS.map((n) => h("button", { type: "button", class: "secondary",
        onclick: () => { form.event_count = n; eventsInput.value = n; updatePlanning(); } }, fmtInt(n)))),
      h("div", { style: "margin-top:8px" }, eventsInput),
      h("p", { class: "muted small" },
        "Quanto maior o número de eventos, maior a capacidade de detectar pequenos desvios estatísticos, ",
        "mas um único experimento pequeno não é suficiente para estabelecer uma conclusão robusta."),
      planningEl,

      h("label", {}, "Quantas pessoas participarão da intenção?"),
      participantsInput,
      h("p", { class: "muted small" }, "Apenas registrado. Não altera nenhum cálculo. Não use nomes reais."),

      h("label", {}, "Duração do período (segundos)"),
      h("div", { class: "chips" }, DURATION_PRESETS.map((m) => h("button", { type: "button", class: "secondary",
        onclick: () => { form.duration_seconds = m * 60; durationInput.value = m * 60; } }, `${m} min`))),
      h("div", { style: "margin-top:8px" }, durationInput),

      methodBlock,

      h("details", {},
        h("summary", {}, "Opções avançadas"),
        h("label", {}, "Hipótese alternativa (fixada agora, antes dos dados)"),
        h("div", { class: "radio-list" },
          radio("alt", "TWO_SIDED", form.alternative_hypothesis, "Bilateral (recomendado)",
            "Testa se a proporção de acertos difere de 50% em qualquer direção.", (v) => (form.alternative_hypothesis = v)),
          radio("alt", "GREATER", form.alternative_hypothesis, "Direcional",
            "Testa apenas se a proporção de acertos é maior que 50%.", (v) => (form.alternative_hypothesis = v)),
        ),
        h("label", {},
          h("input", { type: "checkbox", checked: form.test_mode,
            onchange: (e) => { form.test_mode = e.target.checked; updatePlanning(); } }),
          " Modo teste (dados pseudoaleatórios, sem valor experimental)"),
        h("p", { class: "muted small" }, "Teste estatístico: binomial exato. Nível de significância: α = 0,05."),
      ),

      errorEl,
      h("div", { class: "btn-row" },
        h("a", { class: "btn secondary", href: "#/" }, "VOLTAR"),
        h("button", { onclick: () => continueNew(form, errorEl) }, "CONTINUAR"),
      ),
    ),
  );
  syncMethod();
  updatePlanning();
}

function continueNew(form, errorEl) {
  errorEl.replaceChildren();
  if (form.module === "MODULE_1" && form.target_selection_method === "PARTICIPANT") {
    return viewChooseTargetM1(form);
  }
  return createSession(form, errorEl);
}

function viewChooseTargetM1(form) {
  const errorEl = h("div");
  const pick = (t) => createSession({ ...form, target: t }, errorEl);
  render(
    h("p", { class: "steps" }, "Etapa 1 de 4 — Preparando experimento…"),
    h("h1", {}, "Escolha seu alvo."),
    h("div", { class: "card" },
      h("div", { class: "btn-row" },
        h("button", { class: "target-btn blue", onclick: () => pick(0) }, "🔵 0 — AZUL"),
        h("button", { class: "target-btn red", onclick: () => pick(1) }, "🔴 1 — VERMELHO"),
      ),
      errorEl,
    ),
  );
}

async function createSession(form, errorEl) {
  const body = {
    module: form.module,
    event_count: form.event_count,
    participants_count: form.participants_count,
    duration_seconds: form.duration_seconds,
    target_selection_method: form.module === "CONTROL" ? "SYSTEM_QUANTUM_SHAM" : form.target_selection_method,
    alternative_hypothesis: form.alternative_hypothesis,
    test_mode: form.test_mode,
  };
  if (form.target !== undefined) body.target = form.target;
  try {
    const res = await api.create(body);
    location.hash = `#/sessao/${res.session.session_id}`;
  } catch (err) {
    if (err instanceof ApiError && err.status === 503) return viewSourceFailure(form, err.message);
    errorEl.replaceChildren(errorBox(err));
  }
}

function viewSourceFailure(form, message) {
  render(
    h("h1", {}, "Fonte quântica indisponível"),
    h("div", { class: "card" },
      h("p", { class: "banner bad" }, "Não foi possível obter números da fonte quântica. Nenhum dado pseudoaleatório foi usado."),
      message ? h("p", { class: "muted small" }, message) : null,
      h("div", { class: "btn-row" },
        h("a", { class: "btn secondary", href: "#/" }, "CANCELAR"),
        h("button", { class: "secondary", onclick: () => {
          if (confirm("Esta sessão não terá valor experimental e não entrará nas análises. Criar sessão em modo teste?")) {
            createSession({ ...form, test_mode: true }, h("div"));
          }
        } }, "CRIAR SESSÃO EM MODO TESTE"),
      ),
    ),
  );
}

// ------------------------------------------------------------------ sessão

function stepFor(s) {
  const st = s.state;
  if (s.module === "MODULE_1") {
    if (["CREATED", "PRE_REGISTERED", "TARGET_SELECTED"].includes(st)) return [1, "Preparando experimento…"];
    if (st === "INTENTION_RUNNING") return [2, "Período de intenção."];
    if (["GENERATING", "SEALED"].includes(st)) return [3, "Coletando os dados quânticos."];
    return [4, "Revelação."];
  }
  if (["CREATED", "PRE_REGISTERED", "GENERATING"].includes(st)) return [1, "Preparando experimento…"];
  if (["SEALED", "TARGET_SELECTED"].includes(st)) return [2, "Dados quânticos gerados."];
  if (st === "INTENTION_RUNNING") return [3, s.module === "CONTROL" ? "Período neutro." : "Período de intenção."];
  return [4, "Revelação."];
}

function sessionHeader(s) {
  const [n, label] = stepFor(s);
  const done = ["COMPLETED", "INVALIDATED", "QRNG_ERROR", "CANCELLED"].includes(s.state);
  return [
    s.test_mode ? h("p", { class: "banner test" }, "MODO TESTE — dados pseudoaleatórios. Sem valor experimental.") : null,
    done ? null : h("p", { class: "steps" }, `Etapa ${n} de 4 — ${label}`),
    h("p", { class: "muted small" }, `${MODULES[s.module].title} · ${s.session_id}`),
    s.module === "MODULE_2" ? h("p", { class: "muted small" }, M2_LABEL) : null,
  ];
}

async function viewSession(id) {
  let s;
  try { s = await api.session(id); } catch (err) { return render(h("h1", {}, "Sessão"), errorBox(err)); }
  const handler = {
    PRE_REGISTERED: viewPreRegistered,
    GENERATING: viewGenerating,
    SEALED: viewSealed,
    TARGET_SELECTED: viewTargetSelected,
    INTENTION_RUNNING: viewIntention,
    REVEAL_PENDING: viewRevealPending,
    REVEALED: viewResult,
    ANALYZED: viewResult,
    COMPLETED: viewResult,
    INVALIDATED: viewInvalid,
    QRNG_ERROR: viewQrngError,
    CANCELLED: viewCancelled,
    CREATED: viewPreRegistered,
  }[s.state];
  handler(s);
}

const reload = (s) => viewSession(s.session_id);

async function act(fn, errorEl, s) {
  try { await fn(); reload(s); } catch (err) {
    if (err instanceof ApiError && err.status === 503) {
      errorEl.replaceChildren(h("p", { class: "banner bad" }, "Não foi possível obter números da fonte quântica. Nenhum dado pseudoaleatório foi usado."), errorBox(err));
    } else errorEl.replaceChildren(errorBox(err));
  }
}

function preregCard(s) {
  return h("div", { class: "card" },
    h("p", { class: "big-status" }, "Seu protocolo foi registrado."),
    h("dl", { class: "kv" },
      h("dt", {}, "Eventos"), h("dd", {}, fmtInt(s.planned_event_count)),
      h("dt", {}, "Participantes"), h("dd", {}, s.participants_count),
      h("dt", {}, "Duração"), h("dd", {}, fmtTime(s.planned_duration_seconds)),
      h("dt", {}, "Hipótese"), h("dd", {}, s.alternative_hypothesis === "GREATER" ? "Direcional (acertos > 50%)" : "Bilateral (acertos ≠ 50%)"),
      ...hashLine("SHA-256 do pré-registro", s.preregistration_sha256),
    ),
    h("a", { class: "small", href: `/api/sessions/${s.session_id}/preregistration` }, "Baixar preregistration.json"),
  );
}

function cancelButton(s, errorEl) {
  return h("button", { class: "secondary", onclick: () => {
    if (confirm("Cancelar esta sessão? Ela continuará registrada no histórico como cancelada.")) act(() => api.cancel(s.session_id), errorEl, s);
  } }, "CANCELAR SESSÃO");
}

function viewPreRegistered(s) {
  const errorEl = h("div");
  render(...sessionHeader(s), preregCard(s),
    h("div", { class: "card" },
      h("p", {}, "O próximo passo gera os dados quânticos e os sela imediatamente. Nenhuma informação sobre eles será mostrada."),
      errorEl,
      h("div", { class: "btn-row" },
        cancelButton(s, errorEl),
        h("button", { onclick: () => act(() => api.generate(s.session_id), errorEl, s) }, "GERAR E SELAR OS DADOS"),
      )));
}

function viewGenerating(s) {
  const bar = h("div", { style: "width:0%" });
  const pct = h("p", { class: "muted center" }, "0%");
  render(...sessionHeader(s),
    h("div", { class: "card" },
      h("p", { class: "big-status" }, s.module === "MODULE_1" ? "Intenção concluída." : "Gerando e selando os dados quânticos."),
      s.module === "MODULE_1" ? h("p", {}, "Agora estamos coletando os eventos quânticos.") : null,
      h("div", { class: "progress" }, bar), pct,
    ));
  const update = (cur) => {
    const p = cur.bits_requested ? Math.floor((10 * cur.bits_received) / cur.bits_requested) * 10 : 0;
    bar.style.width = `${p}%`;
    pct.textContent = `${p}%`;
  };
  update(s);
  timers.push(setInterval(async () => {
    try {
      const cur = await api.session(s.session_id);
      if (cur.state !== "GENERATING") return reload(cur);
      update(cur);
    } catch { /* tenta de novo */ }
  }, 1000));
}

function viewSealed(s) {
  const errorEl = h("div");
  const sealed = h("div", { class: "card" },
    h("p", { class: "big-status" }, "Dados gerados e selados."),
    h("dl", { class: "kv" }, ...hashLine("SHA-256 dos eventos", s.events_sha256), ...hashLine("SHA-256 do manifesto", s.manifest_sha256)),
    h("p", { class: "muted small" }, "Recomendação: anote estes códigos fora deste computador."),
  );
  let choose;
  if (s.module === "CONTROL") {
    choose = h("div", { class: "card" },
      h("p", {}, "O sorteio do alvo-placebo não pôde ser concluído."), errorEl,
      h("button", { onclick: () => act(() => api.target(s.session_id), errorEl, s) }, "TENTAR NOVAMENTE"));
  } else if (s.target_selection_method === "SYSTEM_QUANTUM") {
    choose = h("div", { class: "card" },
      h("p", { class: "big-status" }, "Agora o sistema vai sortear o alvo da intenção."), errorEl,
      h("button", { onclick: () => act(() => api.target(s.session_id), errorEl, s) }, "SORTEAR ALVO"));
  } else {
    choose = h("div", { class: "card" },
      h("p", { class: "big-status" }, "Agora escolha o alvo da intenção."),
      h("div", { class: "btn-row" },
        h("button", { class: "target-btn blue", onclick: () => act(() => api.target(s.session_id, 0), errorEl, s) }, "🔵 0 — AZUL"),
        h("button", { class: "target-btn red", onclick: () => act(() => api.target(s.session_id, 1), errorEl, s) }, "🔴 1 — VERMELHO"),
      ), errorEl);
  }
  render(...sessionHeader(s), sealed, choose);
}

function auditCode(s) {
  return h("div", { class: "banner info small" },
    h("div", {}, "Código de auditoria (anote fora deste computador):"),
    h("div", { class: "hash" }, s.audit_code),
    h("div", { class: "muted" }, "Permite ao verificador externo detectar uma reescrita completa do registro de auditoria."));
}

function viewTargetSelected(s) {
  const errorEl = h("div");
  const control = s.module === "CONTROL";
  const minutes = fmtTime(s.planned_duration_seconds);
  render(...sessionHeader(s),
    h("div", { class: "card intention" },
      control
        ? [h("p", { class: "big-status" }, "Período neutro"),
           h("p", {}, `Durante ${minutes}, permaneçam em atividade neutra. Não há alvo a ser focado.`),
           h("p", { class: "muted small" }, "Os dados estão selados.")]
        : [h("p", { class: "big-status" }, "Alvo registrado."),
           h("p", {}, targetBadge(s.target)),
           h("p", {}, s.module === "MODULE_1"
             ? "Agora começa o período de intenção. Nenhum dado quântico foi gerado ainda."
             : `Durante os próximos ${minutes}, concentrem sua atenção no alvo escolhido.`)],
      s.module !== "MODULE_1" ? auditCode(s) : preregCard(s),
      errorEl,
      h("div", { class: "btn-row" },
        s.module === "MODULE_1" ? cancelButton(s, errorEl) : null,
        h("button", { onclick: () => act(() => api.startIntention(s.session_id), errorEl, s) },
          control ? "INICIAR PERÍODO NEUTRO" : "INICIAR PERÍODO DE INTENÇÃO")),
    ));
}

function viewIntention(s) {
  const control = s.module === "CONTROL";
  const timerEl = h("div", { class: "timer" }, fmtTime(s.seconds_remaining ?? 0));
  const errorEl = h("div");
  let remaining = s.seconds_remaining ?? 0;
  let deadline = Date.now() + remaining * 1000;
  let completing = false;

  render(...sessionHeader(s),
    h("div", { class: "card intention" },
      control ? h("p", { class: "big-status" }, "Período neutro") :
        [h("p", { class: "muted" }, "ALVO"), h("p", {}, targetBadge(s.target))],
      h("p", { class: "muted" }, "PARTICIPANTES"),
      h("p", { class: "big-status" }, s.participants_count),
      h("p", { class: "muted" }, "TEMPO RESTANTE"),
      timerEl,
      h("p", { class: "muted small" }, s.module === "MODULE_1" ? "Os dados quânticos serão gerados ao final do período." : "Os dados estão selados."),
      errorEl,
    ));

  async function complete() {
    if (completing) return;
    completing = true;
    try { await api.completeIntention(s.session_id); reload(s); } catch (err) {
      completing = false;
      if (!(err instanceof ApiError && err.status === 409)) errorEl.replaceChildren(errorBox(err));
    }
  }
  timers.push(setInterval(() => {
    remaining = (deadline - Date.now()) / 1000;
    timerEl.textContent = fmtTime(remaining);
    if (remaining <= 0) complete();
  }, 250));
  // ressincroniza com o relógio do servidor
  timers.push(setInterval(async () => {
    try {
      const cur = await api.session(s.session_id);
      if (cur.state !== "INTENTION_RUNNING") return reload(cur);
      if (cur.seconds_remaining !== null) deadline = Date.now() + cur.seconds_remaining * 1000;
    } catch { /* ignora */ }
  }, 5000));
}

function viewRevealPending(s) {
  const errorEl = h("div");
  const btn = h("button", { onclick: async () => {
    btn.disabled = true;
    try {
      await api.reveal(s.session_id);
      reload(s);
    } catch (err) { btn.disabled = false; errorEl.replaceChildren(errorBox(err)); }
  } }, "REVELAR RESULTADO");
  render(...sessionHeader(s),
    h("div", { class: "card center" },
      h("p", { class: "big-status" }, s.module === "MODULE_1" ? "Dados coletados." : "Período concluído."),
      h("p", { class: "muted" }, "Os dados estão selados. Ao revelar, o sistema primeiro confere os hashes e o registro de auditoria."),
      btn, errorEl,
    ));
}

function bars(a) {
  const row = (bit, count) => {
    const p = count / a.n;
    return h("div", { class: "bar-row" },
      h("span", {}, `${TARGETS[bit].emoji} ${bit}`),
      h("div", { class: "bar-track" }, h("div", { class: `bar-fill ${TARGETS[bit].cls}`, style: `width:${100 * p}%` }), h("div", { class: "bar-mid" })),
      h("span", {}, fmtPct(p, 1)));
  };
  return h("div", { class: "bars" }, row(0, a.zeros), row(1, a.ones),
    h("p", { class: "muted small" }, "A linha vertical marca 50%."));
}

function ciScale(a) {
  // Escala centrada em 50%, com margem suficiente para o IC.
  const span = Math.max(0.02, Math.abs(a.ci_95[0] - 0.5), Math.abs(a.ci_95[1] - 0.5)) * 1.25;
  const lo = 0.5 - span, hi = 0.5 + span;
  const pos = (x) => `${(100 * (x - lo)) / (hi - lo)}%`;
  return h("div", {},
    h("p", { class: "small muted" }, "Proporção de acertos com intervalo de confiança de 95% (faixa). Linha central: 50% esperado."),
    h("div", { class: "ci-scale" },
      h("div", { class: "ci-axis" }),
      h("div", { class: "ci-band", style: `left:${pos(a.ci_95[0])};width:calc(${pos(a.ci_95[1])} - ${pos(a.ci_95[0])})` }),
      h("div", { class: "ci-expected" }),
      h("div", { class: "ci-point", style: `left:${pos(a.observed_proportion)}` }),
      h("div", { class: "ci-labels" }, h("span", {}, fmtPct(lo, 1)), h("span", {}, "50%"), h("span", {}, fmtPct(hi, 1)))));
}

async function viewResult(s) {
  let res;
  try { res = await api.result(s.session_id); } catch (err) { return render(...sessionHeader(s), errorBox(err)); }
  if (!res.valid) return viewInvalid(s);
  const a = res.analysis;
  const info = await api.info().catch(() => null);
  const stat = (label, value) => h("div", { class: "stat" }, h("div", { class: "label" }, label), h("div", { class: "value" }, value));
  const dev = `${a.deviation_pp >= 0 ? "+" : ""}${a.deviation_pp.toLocaleString("pt-BR", { maximumFractionDigits: 2, minimumFractionDigits: 2 })} p.p.`;

  render(...sessionHeader(s),
    h("h1", {}, "Experimento concluído."),
    h("div", { class: "card" },
      h("div", { class: "result-grid" },
        stat("Eventos", fmtInt(a.n)),
        stat("Zeros", fmtInt(a.zeros)),
        stat("Uns", fmtInt(a.ones)),
        stat(s.module === "CONTROL" ? "Alvo-placebo" : "Alvo", `${TARGETS[a.target].emoji} ${TARGETS[a.target].label}`),
        stat("Proporção do alvo", fmtPct(a.observed_proportion)),
        stat("Esperado", fmtPct(a.expected_proportion)),
        stat("Desvio", dev),
        stat("p-value", fmtP(a.p_value)),
        stat("IC 95%", `${fmtPct(a.ci_95[0], 1)} – ${fmtPct(a.ci_95[1], 1)}`),
      ),
      h("p", { class: "statement" }, a.result_statement),
      h("p", { class: "muted small" },
        `Teste binomial exato, ${a.alternative_hypothesis === "GREATER" ? "direcional" : "bilateral"}, α = ${String(a.alpha).replace(".", ",")}, definido no pré-registro.`),
      h("p", { class: "muted small" }, info?.p_value_explanation || ""),
      bars(a),
      ciScale(a),
    ),
    h("div", { class: "card" },
      h("dl", { class: "kv" },
        ...hashLine("SHA-256 dos eventos", s.events_sha256),
        ...hashLine("Código de auditoria final", s.audit_code)),
      h("div", { class: "btn-row" },
        h("a", { class: "btn secondary", href: `/api/sessions/${s.session_id}/report.html`, target: "_blank" }, "RELATÓRIO HTML"),
        h("a", { class: "btn secondary", href: `/api/sessions/${s.session_id}/export.json` }, "EXPORTAR JSON"),
        h("a", { class: "btn secondary", href: `/api/sessions/${s.session_id}/events.csv` }, "EXPORTAR CSV"),
      ),
      h("p", { class: "muted small" }, "Este resultado descreve os dados observados. Ele não estabelece uma explicação causal para qualquer desvio observado."),
    ),
    h("div", { class: "btn-row" }, h("a", { class: "btn", href: "#/novo" }, "NOVO EXPERIMENTO"), h("a", { class: "btn secondary", href: "#/historico" }, "HISTÓRICO")),
  );
}

function viewInvalid(s) {
  render(...sessionHeader(s),
    h("div", { class: "card" },
      h("p", { class: "banner bad" }, INVALID_MSG),
      s.invalid_reason ? h("p", { class: "muted small" }, `Motivo técnico: ${s.invalid_reason}`) : null,
      h("p", {}, "Nenhuma estatística é mostrada para esta sessão. Ela continua registrada no histórico."),
      h("a", { class: "btn secondary", href: `/api/sessions/${s.session_id}/report.html`, target: "_blank" }, "RELATÓRIO"),
    ));
}

function viewQrngError(s) {
  render(...sessionHeader(s),
    h("div", { class: "card" },
      h("p", { class: "banner bad" }, "Não foi possível obter números da fonte quântica. Nenhum dado pseudoaleatório foi usado."),
      h("p", {}, "Os dados recebidos até a falha foram preservados exatamente como chegaram. A sessão não será completada."),
      s.invalid_reason ? h("p", { class: "muted small" }, s.invalid_reason) : null,
      h("div", { class: "btn-row" },
        h("a", { class: "btn secondary", href: "#/" }, "VOLTAR"),
        s.test_mode ? null : h("button", { class: "secondary", onclick: () => {
          if (confirm("A nova sessão não terá valor experimental e não entrará nas análises. Continuar em modo teste?")) {
            createSession({ module: s.module, event_count: s.planned_event_count, participants_count: s.participants_count,
              duration_seconds: s.planned_duration_seconds, target_selection_method: s.target_selection_method,
              alternative_hypothesis: s.alternative_hypothesis, test_mode: true,
              target: s.module === "MODULE_1" && s.target_selection_method === "PARTICIPANT" ? s.target : undefined }, h("div"));
          }
        } }, "NOVA SESSÃO EM MODO TESTE"),
      )));
}

function viewCancelled(s) {
  render(...sessionHeader(s), h("div", { class: "card" }, h("p", { class: "big-status" }, "Sessão cancelada."),
    h("p", { class: "muted" }, "Ela continua registrada no histórico."), h("a", { class: "btn", href: "#/novo" }, "NOVO EXPERIMENTO")));
}

// ------------------------------------------------------------------ histórico

function integrityTag(label) {
  const cls = { OK: "ok", INVALIDADA: "bad", AUSENTE: "bad", "ERRO QRNG": "warn", CANCELADA: "neutral" }[label] || "neutral";
  return h("span", { class: `tag ${cls}` }, label);
}

async function viewHistory(testMode = false) {
  let data;
  try { data = await api.history(testMode); } catch (err) { return render(h("h1", {}, "Histórico de experimentos"), errorBox(err)); }
  const rows = [...data.sessions, ...data.missing];
  render(
    h("h1", {}, "Histórico de experimentos"),
    h("div", { class: "tabs" },
      h("button", { class: testMode ? "secondary" : "", onclick: () => viewHistory(false) }, "Experimentais"),
      h("button", { class: testMode ? "" : "secondary", onclick: () => viewHistory(true) }, "Modo teste")),
    testMode ? h("p", { class: "banner test" }, "Sessões pseudoaleatórias. Não entram em nenhuma análise experimental.") : null,
    h("p", { class: "muted small" }, "Todas as sessões são listadas, inclusive as invalidadas, canceladas e com erro. Nenhuma pode ser apagada pela interface."),
    rows.length === 0 ? h("p", {}, "Nenhuma sessão ainda.") :
      h("div", { class: "table-wrap" }, h("table", {},
        h("tr", {}, ["Sessão", "Data (UTC)", "Módulo", "Eventos", "Part.", "Alvo", "Proporção", "p-value", "Integridade"].map((t) => h("th", {}, t))),
        rows.map((r) => h("tr", {},
          h("td", {}, r.present_on_disk === false || !r.state ? r.session_id : h("a", { href: `#/sessao/${r.session_id}` }, r.session_id)),
          h("td", {}, (r.created_at || "").slice(0, 16).replace("T", " ")),
          h("td", {}, MODULES[r.module]?.short || r.module || "—"),
          h("td", {}, r.planned_event_count ? fmtInt(r.planned_event_count) : "—"),
          h("td", {}, r.participants_count ?? "—"),
          h("td", {}, r.target === null || r.target === undefined ? "—" : TARGETS[r.target].emoji),
          h("td", {}, r.observed_proportion === null || r.observed_proportion === undefined ? "—" : fmtPct(r.observed_proportion)),
          h("td", {}, r.p_value === null || r.p_value === undefined ? "—" : fmtP(r.p_value)),
          h("td", {}, integrityTag(r.integrity_label)),
        )))),
    h("div", { class: "btn-row" },
      h("a", { class: "btn secondary", href: `/api/history.csv?test_mode=${testMode}` }, "EXPORTAR CSV"),
      h("a", { class: "btn secondary", href: "#/analise" }, "ANÁLISE DE MÚLTIPLAS SESSÕES")),
  );
}

// ------------------------------------------------------------------ verificar

async function viewVerify(id = null) {
  const data = await api.history(false).catch(() => ({ sessions: [] }));
  const test = await api.history(true).catch(() => ({ sessions: [] }));
  const all = [...data.sessions, ...test.sessions].filter((r) => r.present_on_disk !== false);
  const out = h("div");
  const select = h("select", {}, h("option", { value: "" }, "Escolha uma sessão…"),
    all.map((r) => h("option", { value: r.session_id, selected: r.session_id === id }, `${r.session_id} — ${MODULES[r.module].short} — ${r.state}`)));

  async function run() {
    const sid = select.value;
    if (!sid) return;
    out.replaceChildren(h("p", { class: "muted" }, "Verificando…"));
    try {
      const r = await api.verify(sid);
      const s = await api.session(sid);
      out.replaceChildren(
        h("p", { class: `banner ${r.ok ? "ok" : "bad"}` }, r.ok ? "INTEGRIDADE: OK" : "INTEGRIDADE: FALHOU"),
        h("ul", { class: "checks" }, r.checks.map((c) => h("li", {},
          h("span", { class: `mark ${c.ok ? "ok" : "bad"}` }, c.ok ? "OK" : "FALHOU"),
          h("span", {}, c.name, !c.ok && c.detail ? h("span", { class: "muted small" }, ` — ${c.detail}`) : null)))),
        h("p", {}, "Verificação independente (não usa a aplicação web):"),
        h("pre", {}, `${r.external_command}${s.audit_code ? ` --anchor ${s.audit_code}` : ""}`),
        h("p", { class: "muted small" }, "Use em --anchor os códigos de auditoria que você anotou fora deste computador."),
      );
    } catch (err) { out.replaceChildren(errorBox(err)); }
  }
  select.addEventListener("change", run);
  render(h("h1", {}, "Verificar sessão"),
    h("div", { class: "card" },
      h("p", {}, "Recalcula os hashes, confere a cadeia do registro de auditoria, a sequência de eventos e as estatísticas."),
      select, out));
  if (id) run();
}

// ------------------------------------------------------------- análise múltipla

async function viewAnalysis() {
  let protocols = [];
  let history = { sessions: [] };
  try { [protocols, history] = await Promise.all([api.protocols(), api.history(false)]); } catch (err) { return render(errorBox(err)); }
  const out = h("div");

  function showCombined(res) {
    const c = res.combined;
    out.replaceChildren(
      res.exploratory ? h("p", { class: "banner test" }, res.warning) : h("p", { class: "banner info" }, res.note),
      res.mixed_modules ? h("p", { class: "banner test" }, "As sessões selecionadas pertencem a módulos diferentes.") : null,
      c ? h("div", { class: "card" },
        h("dl", { class: "kv" },
          h("dt", {}, "Sessões incluídas"), h("dd", {}, c.sessions_included),
          h("dt", {}, "Total de eventos"), h("dd", {}, fmtInt(c.total_events)),
          h("dt", {}, "Zeros / Uns"), h("dd", {}, `${fmtInt(c.total_zeros)} / ${fmtInt(c.total_ones)}`),
          h("dt", {}, "Acertos"), h("dd", {}, fmtInt(c.total_hits)),
          h("dt", {}, "Proporção combinada"), h("dd", {}, fmtPct(c.combined_proportion)),
          h("dt", {}, "p-value (binomial)"), h("dd", {}, fmtP(c.p_value)),
          h("dt", {}, "IC 95%"), h("dd", {}, `${fmtPct(c.ci_95[0])} – ${fmtPct(c.ci_95[1])}`)),
        h("p", { class: "statement" }, c.result_statement)) : h("p", {}, "Nenhuma sessão concluída para combinar."),
      h("div", { class: "table-wrap" }, h("table", {},
        h("tr", {}, ["Sessão", "Estado", "Incluída", "Motivo", "Proporção", "p-value"].map((t) => h("th", {}, t))),
        res.sessions.map((r) => h("tr", {},
          h("td", {}, h("a", { href: `#/sessao/${r.session_id}` }, r.session_id)),
          h("td", {}, r.state), h("td", {}, r.included ? "sim" : "não"), h("td", {}, r.reason || ""),
          h("td", {}, r.observed_proportion !== undefined ? fmtPct(r.observed_proportion) : "—"),
          h("td", {}, r.p_value !== undefined ? fmtP(r.p_value) : "—"))))),
    );
  }

  const protoList = protocols.length === 0 ? h("p", {}, "Nenhuma sessão experimental ainda.") :
    protocols.map((p) => h("div", { class: "card" },
      h("p", {}, h("strong", {}, MODULES[p.description?.module]?.title || "Protocolo")),
      h("p", { class: "small muted" },
        `${fmtInt(p.description?.planned_event_count)} eventos · ${fmtTime(p.description?.planned_duration_seconds)} · ` +
        `${p.description?.alternative_hypothesis === "GREATER" ? "direcional" : "bilateral"} · alvo: ${p.description?.target_selection_method}`),
      h("p", { class: "small" }, `${p.sessions} sessão(ões): ` + Object.entries(p.by_state).map(([k, v]) => `${k} ${v}`).join(", ")),
      h("p", { class: "hash small muted" }, p.fingerprint),
      h("button", { class: "secondary", onclick: async () => showCombined(await api.cumulative({ mode: "PROTOCOL", fingerprint: p.fingerprint })) }, "ANALISAR TODAS AS SESSÕES DESTE PROTOCOLO")));

  const checks = history.sessions.filter((r) => r.state === "COMPLETED").map((r) =>
    h("label", {}, h("input", { type: "checkbox", value: r.session_id }), ` ${r.session_id} — ${MODULES[r.module].short}`));

  render(
    h("h1", {}, "Análise de múltiplas sessões"),
    h("h2", {}, "A) Todas as sessões de um protocolo"),
    h("p", { class: "muted small" }, "Inclui todas as sessões concluídas com exatamente os mesmos parâmetros pré-registrados. Nenhuma sessão é omitida. Sessões de teste nunca entram."),
    protoList,
    h("h2", {}, "B) Seleção manual"),
    h("p", { class: "banner test" }, "Esta análise é exploratória e está sujeita a viés de seleção."),
    h("div", { class: "card" }, checks.length ? checks : h("p", {}, "Nenhuma sessão concluída."),
      h("button", { class: "secondary", onclick: async () => {
        const ids = [...app.querySelectorAll("input[type=checkbox]:checked")].map((i) => i.value);
        if (!ids.length) return;
        try { showCombined(await api.cumulative({ mode: "MANUAL", session_ids: ids })); } catch (err) { out.replaceChildren(errorBox(err)); }
      } }, "ANALISAR SELEÇÃO (EXPLORATÓRIA)")),
    out,
  );
}

// ------------------------------------------------------------------ documentação

function viewDocs() {
  const sec = (title, ...items) => [h("h2", {}, title), ...items];
  const ul = (...li) => h("ul", {}, li.map((t) => h("li", {}, t)));
  render(h("div", { class: "docs" },
    h("h1", {}, "Documentação"),
    sec("O que o Daldegan testa",
      h("p", {}, "Se uma intenção consciente direcionada a um resultado binário está associada a uma alteração estatisticamente mensurável na distribuição de bits produzidos por uma fonte quântica de aleatoriedade.")),
    sec("O que ele NÃO testa",
      ul("Não demonstra que oração, fé ou qualquer interpretação filosófica funciona.",
        "Não estabelece causalidade: um resultado significativo isolado mostra apenas que os dados seriam incomuns sob o acaso.",
        "A mecânica quântica não estabelece que a consciência humana seja necessária para o colapso da função de onda.")),
    sec("Os módulos",
      ul("Módulo 1: alvo e intenção primeiro; os dados quânticos são gerados depois.",
        "Módulo 2: os dados são gerados e selados antes; o alvo é escolhido e a intenção acontece sem que ninguém conheça os dados. Conceitualmente interessante porque o resultado já está determinado, mas não observado.",
        "Controle: mesmo fluxo do Módulo 2 com um período neutro, para comparação.")),
    sec("Como ler o p-value",
      h("p", {}, "O p-value indica quão incomum seria um resultado pelo menos tão extremo quanto o observado se apenas o acaso estivesse atuando. Ele não é a probabilidade de a hipótese ser verdadeira."),
      h("p", {}, "Com α = 0,05, cerca de 1 em cada 20 sessões dará resultado “significativo” mesmo sem nenhum efeito real.")),
    sec("Por que o pré-registro importa",
      h("p", {}, "Teste, direção e nível de significância são fixados antes dos dados. Escolhê-los depois de ver o resultado (p-hacking) produz falsos positivos.")),
    sec("Viés de seleção",
      h("p", {}, "Combinar só as sessões “boas” cria um efeito artificial. Por isso a análise por protocolo inclui todas as sessões, e a seleção manual é marcada como exploratória.")),
    sec("Integridade",
      h("p", {}, "Cada sessão guarda os eventos, as respostas brutas da fonte, um manifesto com hashes SHA-256 e um registro de auditoria encadeado. Qualquer alteração invalida a sessão. O verificador externo confere tudo sem usar a aplicação:"),
      h("pre", {}, "python scripts/verify_session.py data/sessions/<SESSÃO> --anchor <CÓDIGO>"),
      h("p", { class: "muted small" }, "Os dados ficam no seu computador. O cegamento depende de você não abrir os arquivos da sessão antes da revelação.")),
    h("p", { class: "statement" }, "Um resultado negativo também é um resultado válido."),
    h("p", { class: "muted small" }, "Mais detalhes no README.md do projeto."),
  ));
}

// ------------------------------------------------------------------ roteador

function route() {
  const hash = location.hash || "#/";
  const [, path, arg] = hash.match(/^#\/([^/]*)\/?(.*)$/) || [];
  if (path === "novo") return viewNew();
  if (path === "sessao" && arg) return viewSession(arg);
  if (path === "historico") return viewHistory(false);
  if (path === "verificar") return viewVerify(arg || null);
  if (path === "analise") return viewAnalysis();
  if (path === "docs") return viewDocs();
  return viewHome();
}

window.addEventListener("hashchange", route);
route();
api.info().then((i) => {
  document.getElementById("version").textContent = `Daldegan ${i.software_version} · protocolo ${i.protocol_version}`;
}).catch(() => {});
