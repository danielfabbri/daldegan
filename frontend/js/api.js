// Cliente mínimo da API. Nenhum resultado é guardado no navegador.

export class ApiError extends Error {
  constructor(status, body) {
    super(typeof body?.detail === "string" ? body.detail : `Erro HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  info: () => request("GET", "/system/info"),
  planning: (n, testMode) => request("GET", `/planning?event_count=${n}&test_mode=${testMode}`),
  create: (body) => request("POST", "/sessions", body),
  session: (id) => request("GET", `/sessions/${id}`),
  generate: (id) => request("POST", `/sessions/${id}/generate`),
  target: (id, target) => request("POST", `/sessions/${id}/target`, target === undefined ? {} : { target }),
  startIntention: (id) => request("POST", `/sessions/${id}/intention/start`),
  completeIntention: (id) => request("POST", `/sessions/${id}/intention/complete`),
  cancel: (id) => request("POST", `/sessions/${id}/cancel`),
  reveal: (id) => request("POST", `/sessions/${id}/reveal`),
  result: (id) => request("GET", `/sessions/${id}/result`),
  verify: (id) => request("GET", `/sessions/${id}/verify`),
  history: (testMode) => request("GET", `/history?test_mode=${testMode}`),
  protocols: () => request("GET", "/analysis/protocols"),
  cumulative: (body) => request("POST", "/analysis/cumulative", body),
};
