"""Verificação de integridade da sessão pela aplicação (SPEC §8.2).

Os detalhes das checagens descrevem apenas divergências de formato/hash/ordem;
nunca incluem contagens ou proporções dos dados, para não quebrar o cegamento.
"""

import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from ..audit.audit_log import verify_chain
from ..audit.hashing import parse_ts, round_floats, sha256_file
from ..models.enums import Module
from ..qrng.bits import MalformedResponse, bytes_to_bits, decode_response
from ..storage.session_store import SessionPaths
from .analysis_builder import RECOMPUTED_FIELDS, build_analysis, parse_events_csv
from .protocol import protocol_fingerprint

FLOAT_TOL = 1e-9

ORDER_MODULE_1 = (
    "PREREGISTERED",
    "TARGET_SELECTED",
    "INTENTION_STARTED",
    "INTENTION_COMPLETED",
    "GENERATION_STARTED",
    "DATA_SEALED",
)
ORDER_MODULE_2 = (
    "PREREGISTERED",
    "GENERATION_STARTED",
    "DATA_SEALED",
    "TARGET_SELECTED",
    "INTENTION_STARTED",
    "INTENTION_COMPLETED",
)


@dataclass
class IntegrityReport:
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        return ok

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(c["ok"] for c in self.checks)

    @property
    def failures(self) -> list[str]:
        return [f"{c['name']}: {c['detail']}" if c["detail"] else c["name"] for c in self.checks if not c["ok"]]

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checks": self.checks}


def read_raw_blocks(path: Path) -> tuple[list[dict], list[str]]:
    blocks, errors = [], []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for i, line in enumerate(f, start=1):
                line = line.rstrip("\n")
                if not line:
                    continue
                try:
                    blocks.append(json.loads(line))
                except json.JSONDecodeError:
                    errors.append(f"qrng_raw.jsonl: linha {i} ilegível")
    except OSError as exc:
        errors.append(f"qrng_raw.jsonl ilegível: {exc}")
    return blocks, errors


def bits_and_timestamps_from_raw(blocks: list[dict]) -> tuple[list[int], list[str]]:
    bits: list[int] = []
    ts: list[str] = []
    for block in blocks:
        p = block["request_params"]
        data = decode_response(block["body"], p["type"], p["length"], p.get("size"))
        new = bytes_to_bits(data)
        bits.extend(new)
        ts.extend([block["response_timestamp"]] * len(new))
    return bits, ts


def _load_json(path: Path) -> dict | None:
    try:
        obj = json.loads(path.read_bytes().decode("utf-8"))
        return obj if isinstance(obj, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _single(entries_by_event: dict, name: str) -> dict | None:
    found = entries_by_event.get(name, [])
    return found[0] if len(found) == 1 else None


def _equal(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        try:
            return abs(float(a) - float(b)) <= FLOAT_TOL
        except (TypeError, ValueError):
            return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def timeline_from_audit(entries: list[dict]) -> dict:
    def ts(event):
        for e in entries:
            if e["event"] == event:
                return e["timestamp"]
        return None

    return {
        "target_selected_timestamp": ts("TARGET_SELECTED"),
        "intention_started_at": ts("INTENTION_STARTED"),
        "intention_completed_at": ts("INTENTION_COMPLETED"),
    }


def verify_session(
    paths: SessionPaths,
    record: dict | None = None,
    *,
    require_complete_timeline: bool = True,
) -> IntegrityReport:
    """require_complete_timeline=False permite verificar sessões seladas que ainda
    não concluíram a intenção (as etapas existentes precisam estar em ordem)."""
    """Executa todas as checagens. `record` é a linha do índice SQLite (opcional)."""
    r = IntegrityReport()
    session_id = paths.root.name

    required = {
        "preregistration.json": paths.preregistration,
        "manifest.json": paths.manifest,
        "events.csv": paths.events,
        "qrng_raw.jsonl": paths.qrng_raw,
        "audit.log": paths.audit,
    }
    missing = [name for name, p in required.items() if not p.exists()]
    if not r.add("arquivos_presentes", not missing, f"ausentes: {', '.join(missing)}" if missing else ""):
        return r

    # --- cadeia do audit log ---------------------------------------------
    chain = verify_chain(paths.audit)
    r.add("cadeia_audit_log", chain.ok, "; ".join(chain.errors))
    entries = chain.entries
    by_event: dict[str, list[dict]] = {}
    for e in entries:
        by_event.setdefault(e.get("event"), []).append(e)
    if entries:
        r.add(
            "audit_log_session_id",
            all(e.get("session_id") == session_id for e in entries),
            "entradas com session_id divergente",
        )

    prereg = _load_json(paths.preregistration)
    manifest = _load_json(paths.manifest)
    if not r.add("json_legivel", prereg is not None and manifest is not None, "pré-registro ou manifesto ilegível"):
        return r

    # --- hashes ------------------------------------------------------------
    prereg_sha = sha256_file(paths.preregistration)
    manifest_sha = sha256_file(paths.manifest)
    events_sha = sha256_file(paths.events)
    raw_sha = sha256_file(paths.qrng_raw)

    pre_entry = _single(by_event, "PREREGISTERED")
    sealed_entry = _single(by_event, "DATA_SEALED")
    if not r.add("eventos_de_auditoria", pre_entry is not None and sealed_entry is not None,
                 "PREREGISTERED/DATA_SEALED ausentes ou duplicados"):
        return r
    pm = pre_entry["metadata"]
    sm = sealed_entry["metadata"]

    expected_prereg = {pm.get("preregistration_sha256"), manifest.get("preregistration_sha256"),
                       sm.get("preregistration_sha256")}
    if record:
        expected_prereg.add(record.get("preregistration_sha256"))
    r.add("hash_preregistro", expected_prereg == {prereg_sha}, "SHA-256 do pré-registro não confere")

    expected_manifest = {sm.get("manifest_sha256")}
    if record:
        expected_manifest.add(record.get("manifest_sha256"))
    r.add("hash_manifesto", expected_manifest == {manifest_sha}, "SHA-256 do manifesto não confere")

    expected_events = {manifest.get("events_sha256"), sm.get("events_sha256")}
    if record:
        expected_events.add(record.get("events_sha256"))
    r.add("hash_eventos", expected_events == {events_sha}, "SHA-256 de events.csv não confere")

    r.add("hash_qrng_raw", {manifest.get("qrng_raw_sha256"), sm.get("qrng_raw_sha256")} == {raw_sha},
          "SHA-256 de qrng_raw.jsonl não confere")

    # --- conteúdo do pré-registro --------------------------------------------
    module = prereg.get("module")
    try:
        module = Module(module)
    except ValueError:
        r.add("modulo_valido", False, f"módulo desconhecido: {module!r}")
        return r
    r.add("preregistro_session_id", prereg.get("session_id") == session_id == manifest.get("session_id"),
          "session_id divergente entre diretório, pré-registro e manifesto")
    try:
        fp_ok = protocol_fingerprint(prereg) == prereg.get("protocol_fingerprint") == pm.get("protocol_fingerprint")
    except KeyError:
        fp_ok = False
    r.add("fingerprint_protocolo", fp_ok, "fingerprint do protocolo não confere")
    if module == Module.MODULE_1:
        r.add("alvo_preregistrado", prereg.get("planned_target") in (0, 1), "Módulo 1 exige alvo pré-registrado")
    else:
        r.add("alvo_preregistrado", prereg.get("planned_target") is None,
              "Módulos 2/Controle não podem ter alvo pré-registrado")

    test_mode = prereg.get("test_mode")
    source_type = (prereg.get("random_source") or {}).get("source_type")
    r.add(
        "fonte_consistente",
        source_type == manifest.get("source_type")
        and (source_type == "PSEUDORANDOM_TEST") == bool(test_mode) == session_id.startswith("DALTEST-"),
        "fonte declarada, fonte usada e modo da sessão divergem",
    )

    # --- eventos -------------------------------------------------------------
    bits, ts, fmt_errors = parse_events_csv(paths.events, session_id)
    r.add("formato_eventos", not fmt_errors, "; ".join(fmt_errors))
    n_planned = prereg.get("planned_event_count")
    r.add(
        "contagem_eventos",
        len(bits) == manifest.get("event_count") == n_planned == manifest.get("number_of_bits_received"),
        "número de eventos difere do manifesto/pré-registro",
    )
    r.add("sessao_completa", manifest.get("partial") is False, "coleta parcial")

    blocks, raw_errors = read_raw_blocks(paths.qrng_raw)
    try:
        raw_bits, raw_ts = bits_and_timestamps_from_raw(blocks)
        raw_bits, raw_ts = raw_bits[: len(bits)], raw_ts[: len(bits)]
        match = not raw_errors and raw_bits == bits and raw_ts == ts and len(raw_bits) == len(bits)
        detail = "; ".join(raw_errors) or "bits de events.csv não correspondem às respostas brutas"
    except (MalformedResponse, KeyError, TypeError) as exc:
        match, detail = False, f"qrng_raw.jsonl inválido: {exc}"
    r.add("eventos_correspondem_ao_bruto", match, detail)

    # --- alvo ----------------------------------------------------------------
    target_entries = by_event.get("TARGET_SELECTED", [])
    target = target_entries[0]["metadata"].get("target") if len(target_entries) == 1 else None
    target_ok = len(target_entries) == 1 and target in (0, 1)
    if not target_entries and not require_complete_timeline and module != Module.MODULE_1:
        target_ok = True  # alvo ainda não escolhido
    if module == Module.MODULE_1:
        target_ok = target_ok and target == prereg.get("planned_target")
    if record and record.get("target") is not None:
        target_ok = target_ok and record.get("target") == target
    r.add("alvo_consistente", target_ok, "alvo divergente entre pré-registro, audit log e índice")

    # --- índice vs. pré-registro ---------------------------------------------
    if record:
        pairs = {
            "module": "module",
            "participants_count": "participants_count",
            "planned_duration_seconds": "planned_duration_seconds",
            "planned_event_count": "planned_event_count",
            "alternative_hypothesis": "alternative_hypothesis",
            "alpha": "alpha",
            "target_selection_method": "target_selection_method",
        }
        diverging = [k for k, rk in pairs.items() if prereg.get(k) != record.get(rk)]
        if bool(record.get("test_mode")) != bool(test_mode):
            diverging.append("test_mode")
        r.add("indice_confere_preregistro", not diverging, f"campos divergentes: {', '.join(diverging)}")

    # --- cronologia ------------------------------------------------------------
    order = ORDER_MODULE_1 if module == Module.MODULE_1 else ORDER_MODULE_2
    present = [name for name in order if name in by_event]
    timeline_ok = present == list(order) if require_complete_timeline else present == list(order[: len(present)])
    seqs = []
    for name in present:
        found = by_event[name]
        if len(found) != 1:
            timeline_ok = False
            break
        seqs.append(found[0]["seq"])
    timeline_ok = timeline_ok and seqs == sorted(seqs)
    started = _single(by_event, "INTENTION_STARTED")
    completed = _single(by_event, "INTENTION_COMPLETED")
    duration = prereg.get("planned_duration_seconds")
    if timeline_ok and started and completed:
        elapsed = parse_ts(completed["timestamp"]) - parse_ts(started["timestamp"])
        timeline_ok = (
            elapsed >= timedelta(seconds=duration)
            and started["metadata"].get("duration_seconds") == duration
        )
    r.add("cronologia", timeline_ok, "ordem dos eventos ou duração da intenção inválida")

    # --- análise (se já existir) -------------------------------------------------
    if paths.analysis.exists():
        analysis = _load_json(paths.analysis)
        done = _single(by_event, "ANALYSIS_COMPLETED")
        ok = analysis is not None and done is not None
        detail = "analysis.json ilegível ou ANALYSIS_COMPLETED ausente"
        if ok:
            ok = sha256_file(paths.analysis) == done["metadata"].get("analysis_sha256")
            detail = "SHA-256 de analysis.json não confere"
        if ok and target in (0, 1) and not fmt_errors:
            recomputed = round_floats(
                build_analysis(
                    preregistration=prereg,
                    manifest=manifest,
                    bits=bits,
                    target=target,
                    timeline=timeline_from_audit(entries),
                    hashes={
                        "preregistration_sha256": prereg_sha,
                        "manifest_sha256": manifest_sha,
                        "events_sha256": events_sha,
                    },
                    audit_head_hash="",
                    analyzed_timestamp="",
                )
            )
            diverging = [k for k in RECOMPUTED_FIELDS if not _equal(recomputed.get(k), analysis.get(k))]
            ok = not diverging
            detail = f"estatísticas divergentes: {', '.join(diverging)}"
        r.add("analise_confere", ok, detail)

    return r
