"""Única forma de serializar uma sessão para a API (SPEC §8.1).

Usa allowlist: antes de REVEALED nada derivado dos dados é exposto. O alvo
placebo da sessão Controle também fica oculto até a revelação.
"""

from ..audit.hashing import parse_ts
from ..clock import Clock
from ..models.enums import REVEALED_STATES, Module, State

ALWAYS = (
    "session_id",
    "module",
    "state",
    "created_at",
    "planned_event_count",
    "planned_duration_seconds",
    "participants_count",
    "target_selection_method",
    "alternative_hypothesis",
    "alpha",
    "protocol_fingerprint",
    "target_selected_at",
    "intention_started_at",
    "intention_ends_at",
    "intention_completed_at",
    "bits_requested",
    "bits_received",
    "integrity_status",
    "invalid_reason",
)
HASHES = ("preregistration_sha256", "events_sha256", "manifest_sha256")
RESULT_FIELDS = ("observed_proportion", "p_value", "significant")


def _mask(h: str | None, full: bool) -> str | None:
    if not h or full:
        return h
    return f"{h[:8]}…{h[-8:]}"


def serialize(record: dict, clock: Clock, show_full_hash: bool = True) -> dict:
    state = State(record["state"])
    revealed = state in REVEALED_STATES
    out = {k: record.get(k) for k in ALWAYS}
    out["test_mode"] = bool(record.get("test_mode"))
    for h in HASHES:
        out[h] = _mask(record.get(h), show_full_hash)

    hide_target = record["module"] == str(Module.CONTROL) and not revealed
    out["target"] = None if hide_target else record.get("target")

    remaining = None
    if state == State.INTENTION_RUNNING and record.get("intention_ends_at") and not record.get("intention_completed_at"):
        remaining = max(0.0, (parse_ts(record["intention_ends_at"]) - clock.now()).total_seconds())
    out["seconds_remaining"] = remaining
    out["result_available"] = revealed

    if revealed:
        for k in RESULT_FIELDS:
            out[k] = record.get(k)
        if out.get("significant") is not None:
            out["significant"] = bool(out["significant"])
    else:
        for k in RESULT_FIELDS:
            out[k] = None
    return out
