"""Relatório HTML autocontido por sessão (SPEC §11)."""

import json
from html import escape
from pathlib import Path

from ..audit.audit_log import read_entries
from ..environment import collect_environment
from ..models.enums import Module
from ..statistics.binomial import P_VALUE_EXPLANATION
from ..storage.session_store import SessionPaths
from ..version import PROTOCOL_VERSION, SOFTWARE_VERSION

FOOTER = (
    "Este relatório descreve os dados observados. Ele não estabelece uma explicação "
    "causal para qualquer desvio observado."
)
INVALID_MESSAGE = "SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada."

MODULE_LABELS = {
    "MODULE_1": "Módulo 1 — Intenção antes da geração",
    "MODULE_2": "Módulo 2 — Intenção depois da geração (dados gerados antes da intenção e mantidos cegos até a conclusão da intenção)",
    "CONTROL": "Controle — período neutro",
}
TARGET_LABELS = {0: "0 — AZUL", 1: "1 — VERMELHO"}

LIMITATIONS = [
    "Um único experimento não é suficiente para estabelecer uma conclusão robusta.",
    "Um resultado estatisticamente significativo isolado não demonstra causalidade.",
    "Múltiplas sessões e múltiplas análises aumentam a chance de resultados significativos por acaso (múltiplas comparações).",
    "O cegamento é procedimental: quem tem acesso ao computador pode abrir os arquivos da sessão.",
    "A cadeia de hashes detecta alterações parciais, mas pode ser reescrita por quem controla o disco; para garantia externa, registre os hashes fora desta máquina.",
    "A qualidade da aleatoriedade depende da fonte externa declarada no manifesto.",
]


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _fmt_pct(x: float) -> str:
    return f"{100 * x:.2f}%".replace(".", ",")


def _fmt_int(x: int) -> str:
    return f"{x:,}".replace(",", ".")


def _rows(pairs) -> str:
    return "".join(f"<tr><th>{escape(str(k))}</th><td>{escape(str(v))}</td></tr>" for k, v in pairs)


def _section(n: int, title: str, body: str) -> str:
    return f"<section><h2>{n}. {escape(title)}</h2>{body}</section>"


def render_report(paths: SessionPaths, record: dict, integrity) -> str:
    prereg = load_json(paths.preregistration) or {}
    manifest = load_json(paths.manifest) or {}
    analysis = load_json(paths.analysis) if paths.analysis.exists() else None
    entries = read_entries(paths.audit) if paths.audit.exists() else []
    valid = integrity.ok and analysis is not None

    test_banner = (
        '<p class="banner test">MODO TESTE — dados pseudoaleatórios. Esta sessão não tem valor experimental.</p>'
        if record.get("test_mode") else ""
    )
    status_banner = "" if valid else f'<p class="banner invalid">{escape(INVALID_MESSAGE)}</p>'

    sections = []
    sections.append(_section(1, "Identificação da sessão", "<table>" + _rows([
        ("Sessão", record["session_id"]),
        ("UUID", record.get("session_uuid")),
        ("Módulo", MODULE_LABELS.get(record["module"], record["module"])),
        ("Estado", record["state"]),
        ("Criada em (UTC)", record["created_at"]),
    ]) + "</table>"))

    sections.append(_section(2, "Protocolo (pré-registro)", "<table>" + _rows([
        ("Versão do protocolo", prereg.get("protocol_version")),
        ("Teste estatístico", prereg.get("statistical_test")),
        ("Medida", "acertos (bit igual ao alvo)"),
        ("Hipótese nula", prereg.get("null_hypothesis")),
        ("Hipótese alternativa", prereg.get("alternative_hypothesis")),
        ("α", prereg.get("alpha")),
        ("Duração planejada (s)", prereg.get("planned_duration_seconds")),
        ("Método de seleção do alvo", prereg.get("target_selection_method")),
        ("Fingerprint do protocolo", prereg.get("protocol_fingerprint")),
    ]) + "</table>"))

    sections.append(_section(3, "Fonte de aleatoriedade", "<table>" + _rows([
        ("Tipo", manifest.get("source_type")),
        ("Nome", manifest.get("source_name")),
        ("Endpoint", manifest.get("source_endpoint")),
        ("Tipo de dado", manifest.get("source_data_type")),
        ("Requisições", manifest.get("qrng_requests")),
        ("Primeira requisição", manifest.get("request_timestamp")),
        ("Última resposta", manifest.get("response_timestamp")),
        ("Transformação em bits", manifest.get("bit_extraction")),
    ]) + "</table>"))

    sections.append(_section(4, "Número de eventos", "<table>" + _rows([
        ("Planejados", prereg.get("planned_event_count")),
        ("Recebidos", manifest.get("number_of_bits_received")),
    ]) + "</table>"))

    labels = prereg.get("participant_labels") or []
    sections.append(_section(5, "Participantes", "<table>" + _rows([
        ("Número declarado", prereg.get("participants_count")),
        ("Rótulos", ", ".join(labels)),
    ]) + "</table><p class=note>O número de participantes é apenas registrado; não entra em nenhum cálculo.</p>"))

    target = record.get("target")
    sections.append(_section(6, "Alvo", "<table>" + _rows([
        ("Alvo", TARGET_LABELS.get(target, "—") if valid or record["module"] != str(Module.CONTROL) else "—"),
        ("Método", record.get("target_selection_method")),
        ("Registrado em", record.get("target_selected_at")),
    ]) + "</table>"))

    timeline = "".join(
        f"<tr><td>{e.get('seq')}</td><td>{escape(str(e.get('timestamp')))}</td><td>{escape(str(e.get('event')))}</td></tr>"
        for e in entries if e.get("event") != "QRNG_BLOCK_RECEIVED"
    )
    sections.append(_section(7, "Cronologia", f"<table><tr><th>#</th><th>UTC</th><th>Evento</th></tr>{timeline}</table>"))

    checks = "".join(
        f"<tr><td>{'OK' if c['ok'] else 'FALHOU'}</td><td>{escape(c['name'])}</td><td>{escape(c['detail'] if not c['ok'] else '')}</td></tr>"
        for c in integrity.checks
    )
    sections.append(_section(8, "Integridade", f"<p><strong>{'INTEGRIDADE: OK' if integrity.ok else 'INTEGRIDADE: FALHOU'}</strong></p><table>{checks}</table>"))

    if valid:
        a = analysis
        result_body = "<table>" + _rows([
            ("Eventos", _fmt_int(a["n"])),
            ("Zeros", _fmt_int(a["zeros"])),
            ("Uns", _fmt_int(a["ones"])),
            ("Alvo", TARGET_LABELS[a["target"]]),
            ("Acertos", _fmt_int(a["hits"])),
            ("Proporção do alvo", _fmt_pct(a["observed_proportion"])),
            ("Esperado", _fmt_pct(a["expected_proportion"])),
            ("Desvio", f"{a['deviation_pp']:+.2f} ponto percentual".replace(".", ",")),
        ]) + f"</table><p class=statement>{escape(a['result_statement'])}</p>"
        stats_body = "<table>" + _rows([
            ("Teste", a["statistical_test"]),
            ("Hipótese alternativa", a["alternative_hypothesis"]),
            ("α", a["alpha"]),
            ("p-value", f"{a['p_value']:.6g}"),
            ("IC 95% (Clopper-Pearson)", f"{_fmt_pct(a['ci_95'][0])} – {_fmt_pct(a['ci_95'][1])}"),
            ("z-score", f"{a['z_score']:.4f}"),
            ("Proporção de uns", _fmt_pct(a["proportion_of_ones"])),
        ]) + f"</table><p class=note>{escape(P_VALUE_EXPLANATION)}</p>"
    else:
        result_body = f"<p class=statement>{escape(INVALID_MESSAGE)}</p>"
        stats_body = "<p>Nenhuma estatística é apresentada para sessões cuja integridade não foi confirmada.</p>"
        if record.get("invalid_reason"):
            result_body += f"<p class=note>Motivo: {escape(record['invalid_reason'])}</p>"
    sections.append(_section(9, "Resultado", result_body))
    sections.append(_section(10, "Estatística", stats_body))
    sections.append(_section(11, "Limitações", "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in LIMITATIONS) + "</ul>"))

    sections.append(_section(12, "Hashes (SHA-256)", "<table>" + _rows([
        ("preregistration.json", record.get("preregistration_sha256")),
        ("manifest.json", record.get("manifest_sha256")),
        ("events.csv", record.get("events_sha256")),
        ("qrng_raw.jsonl", manifest.get("qrng_raw_sha256")),
        ("Última entrada do audit.log", entries[-1]["hash_current_log_entry"] if entries else None),
    ]) + "</table>"))

    env = prereg.get("environment") or collect_environment()
    sections.append(_section(13, "Versão do software", "<table>" + _rows([
        ("Software (sessão)", prereg.get("software_version")),
        ("Protocolo (sessão)", prereg.get("protocol_version")),
        ("Git commit", env.get("git_commit")),
        ("Python", env.get("python_version")),
        ("Sistema", env.get("os")),
        ("Relatório gerado por", f"Daldegan {SOFTWARE_VERSION} / protocolo {PROTOCOL_VERSION}"),
    ]) + "</table>"))

    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Relatório {escape(record['session_id'])}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:860px;margin:0 auto;padding:16px;color:#1d2330;background:#fff;line-height:1.45}}
h1{{font-size:1.5rem}}h2{{font-size:1.1rem;border-bottom:1px solid #d6dae3;padding-bottom:4px;margin-top:28px}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}th,td{{text-align:left;padding:4px 8px;border-bottom:1px solid #eef0f4;vertical-align:top;word-break:break-word}}
th{{width:34%;color:#4a5263;font-weight:600}}.note{{color:#4a5263;font-size:.88rem}}.statement{{font-weight:600;font-size:1.05rem}}
.banner{{padding:10px 12px;border-radius:6px;font-weight:600}}.test{{background:#fff4d6;color:#6b4e00}}.invalid{{background:#fde2e2;color:#8a1c1c}}
footer{{margin-top:32px;padding-top:12px;border-top:2px solid #1d2330;font-weight:600}}
</style></head><body>
<h1>DALDEGAN — Relatório da sessão {escape(record['session_id'])}</h1>
{test_banner}{status_banner}
{''.join(sections)}
<footer>{escape(FOOTER)}</footer>
</body></html>
"""
