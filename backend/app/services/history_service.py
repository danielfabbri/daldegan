"""Histórico, exportações e análise acumulada (SPEC §7.5, §9, §10.2)."""

import csv
import io

from ..audit.audit_log import read_entries
from ..errors import Blinded, IllegalTransition
from ..models.enums import REVEALED_STATES, Alternative, State
from ..statistics.binomial import DEFAULT_ALPHA, binomial_analysis
from . import blind_view, report_service
from .integrity import verify_session
from .protocol import protocol_description
from .session_service import SessionService

EXPLORATORY_WARNING = "Esta análise é exploratória e está sujeita a viés de seleção."

INTEGRITY_LABELS = {
    "OK": "OK",
    "FAILED": "INVALIDADA",
    "QRNG_ERROR": "ERRO QRNG",
    "PENDING": "pendente",
}


def _integrity_label(record: dict) -> str:
    if record["state"] == str(State.CANCELLED):
        return "CANCELADA"
    return INTEGRITY_LABELS.get(record.get("integrity_status") or "PENDING", record.get("integrity_status"))


def history(svc: SessionService, test_mode: bool) -> dict:
    rows = []
    for record in svc.index.list_sessions(test_mode=test_mode):
        view = blind_view.serialize(record, svc.clock, svc.settings.show_full_hash)
        view["integrity_label"] = _integrity_label(record)
        view["present_on_disk"] = svc.paths(record["session_id"]).root.exists()
        if not view["present_on_disk"]:
            view["integrity_label"] = "AUSENTE"
        rows.append(view)

    # Sessões registradas no log global mas ausentes do índice (ex.: removidas manualmente).
    known = {r["session_id"] for r in rows}
    missing = []
    for entry in read_entries(svc.settings.global_audit_path):
        sid = entry.get("session_id")
        if entry.get("event") == "SESSION_REGISTERED" and sid not in known:
            if bool(entry.get("metadata", {}).get("test_mode")) == test_mode:
                missing.append({"session_id": sid, "created_at": entry.get("timestamp"),
                                "module": entry.get("metadata", {}).get("module"), "integrity_label": "AUSENTE"})
                known.add(sid)
    return {"sessions": rows, "missing": missing}


def history_csv(svc: SessionService, test_mode: bool) -> str:
    data = history(svc, test_mode)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["session_id", "data_utc", "modulo", "eventos", "participantes", "alvo",
                "proporcao_alvo", "p_value", "integridade", "estado", "modo_teste"])
    for r in data["sessions"]:
        w.writerow([r["session_id"], r["created_at"], r["module"], r["planned_event_count"],
                    r["participants_count"], "" if r["target"] is None else r["target"],
                    "" if r["observed_proportion"] is None else r["observed_proportion"],
                    "" if r["p_value"] is None else r["p_value"],
                    r["integrity_label"], r["state"], int(r["test_mode"])])
    for r in data["missing"]:
        w.writerow([r["session_id"], r["created_at"], r["module"], "", "", "", "", "", "AUSENTE", "", int(test_mode)])
    return buf.getvalue()


def _require_finished(record: dict) -> None:
    if State(record["state"]) not in (State.COMPLETED, State.INVALIDATED):
        if State(record["state"]) not in REVEALED_STATES:
            raise Blinded("dados cegos até a revelação")
        raise IllegalTransition("sessão ainda em processamento")


def export_json(svc: SessionService, session_id: str) -> dict:
    record = svc.get_record(session_id)
    _require_finished(record)
    paths = svc.paths(session_id)
    report = verify_session(paths, record)
    return {
        "session": blind_view.serialize(record, svc.clock, True),
        "preregistration": report_service.load_json(paths.preregistration),
        "manifest": report_service.load_json(paths.manifest),
        "analysis": report_service.load_json(paths.analysis) if paths.analysis.exists() else None,
        "audit_log": read_entries(paths.audit),
        "integrity": report.to_dict(),
    }


def report_html(svc: SessionService, session_id: str) -> str:
    record = svc.get_record(session_id)
    _require_finished(record)
    paths = svc.paths(session_id)
    integrity = verify_session(paths, record)
    if record["state"] == str(State.COMPLETED) and integrity.ok and paths.report.exists():
        return paths.report.read_text(encoding="utf-8")
    # Sessão invalidada (ou adulterada depois de concluída): relatório gerado na hora, sem estatísticas.
    return report_service.render_report(paths, record, integrity)


def events_csv(svc: SessionService, session_id: str) -> bytes:
    record = svc.get_record(session_id)
    if State(record["state"]) not in REVEALED_STATES:
        raise Blinded("dados cegos até a revelação")
    return svc.paths(session_id).events.read_bytes()


def result(svc: SessionService, session_id: str) -> dict:
    record = svc.get_record(session_id)
    state = State(record["state"])
    if state == State.INVALIDATED:
        return {"valid": False, "message": report_service.INVALID_MESSAGE,
                "reason": record.get("invalid_reason"), "session": blind_view.serialize(record, svc.clock)}
    if state not in REVEALED_STATES:
        raise Blinded("dados cegos até a revelação")
    analysis = svc.read_analysis(session_id)
    return {"valid": analysis is not None, "analysis": analysis,
            "session": blind_view.serialize(record, svc.clock, svc.settings.show_full_hash)}


# ------------------------------------------------------------ análise acumulada

def list_protocols(svc: SessionService) -> list[dict]:
    groups: dict[str, dict] = {}
    for record in svc.index.list_sessions(test_mode=False):
        fp = record.get("protocol_fingerprint")
        if not fp:
            continue
        g = groups.setdefault(fp, {"fingerprint": fp, "description": None, "sessions": 0, "by_state": {}})
        g["sessions"] += 1
        g["by_state"][record["state"]] = g["by_state"].get(record["state"], 0) + 1
        if g["description"] is None:
            prereg = report_service.load_json(svc.paths(record["session_id"]).preregistration)
            if prereg:
                g["description"] = protocol_description(prereg)
    return sorted(groups.values(), key=lambda g: -g["sessions"])


def _session_contribution(svc: SessionService, record: dict) -> dict:
    row = {"session_id": record["session_id"], "module": record["module"], "state": record["state"],
           "created_at": record["created_at"], "included": False, "reason": None}
    if record["state"] != str(State.COMPLETED):
        row["reason"] = f"estado {record['state']}"
        return row
    paths = svc.paths(record["session_id"])
    if not verify_session(paths, record).ok:
        row["reason"] = "integridade falhou"
        return row
    a = report_service.load_json(paths.analysis)
    row.update(included=True, n=a["n"], hits=a["hits"], target=a["target"],
               observed_proportion=a["observed_proportion"], p_value=a["p_value"])
    return row


def _combine(rows: list[dict], alternative: Alternative, alpha: float) -> dict | None:
    included = [r for r in rows if r["included"]]
    if not included:
        return None
    n = sum(r["n"] for r in included)
    hits = sum(r["hits"] for r in included)
    ones = sum(r["hits"] if r["target"] == 1 else r["n"] - r["hits"] for r in included)
    stats = binomial_analysis(n=n, hits=hits, alternative=alternative, alpha=alpha)
    return {"sessions_included": len(included), "total_events": n, "total_hits": hits,
            "total_ones": ones, "total_zeros": n - ones, "combined_proportion": stats["observed_proportion"],
            **stats}


def cumulative(svc: SessionService, mode: str, fingerprint: str | None, session_ids: list[str] | None) -> dict:
    if mode == "PROTOCOL":
        records = [r for r in svc.index.list_sessions(test_mode=False) if r.get("protocol_fingerprint") == fingerprint]
        if not records:
            return {"mode": mode, "fingerprint": fingerprint, "exploratory": False, "sessions": [], "combined": None}
        prereg = report_service.load_json(svc.paths(records[0]["session_id"]).preregistration)
        alternative = Alternative(prereg["alternative_hypothesis"])
        alpha = prereg["alpha"]
        rows = [_session_contribution(svc, r) for r in records]
        return {"mode": mode, "fingerprint": fingerprint, "exploratory": False,
                "protocol": protocol_description(prereg),
                "note": "Inclui todas as sessões concluídas deste protocolo. Nenhuma sessão é omitida.",
                "sessions": rows, "combined": _combine(rows, alternative, alpha)}

    rows = []
    for sid in dict.fromkeys(session_ids or []):
        record = svc.get_record(sid)
        if record["test_mode"]:
            raise IllegalTransition("sessões de teste não entram em análises experimentais")
        rows.append(_session_contribution(svc, record))
    modules = {r["module"] for r in rows}
    return {"mode": mode, "exploratory": True, "warning": EXPLORATORY_WARNING,
            "mixed_modules": len(modules) > 1, "modules": sorted(modules),
            "sessions": rows, "combined": _combine(rows, Alternative.TWO_SIDED, DEFAULT_ALPHA)}

