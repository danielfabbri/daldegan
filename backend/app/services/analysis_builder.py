"""Leitura de eventos e construção de analysis.json (SPEC §4.5, §4.8)."""

from pathlib import Path

from ..models.enums import Alternative
from ..statistics.binomial import binomial_analysis
from ..version import PROTOCOL_VERSION, SOFTWARE_VERSION

EVENTS_HEADER = "event_id,sequence_number,bit,timestamp_utc"


def build_events_csv(session_id: str, bits: list[int], timestamps: list[str]) -> bytes:
    lines = [EVENTS_HEADER]
    for i, (bit, ts) in enumerate(zip(bits, timestamps, strict=True), start=1):
        lines.append(f"{session_id}-{i:06d},{i},{bit},{ts}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_events_csv(path: Path, session_id: str) -> tuple[list[int], list[str], list[str]]:
    """Devolve (bits, timestamps, erros). Erros descrevem apenas o formato, nunca o conteúdo."""
    errors: list[str] = []
    bits: list[int] = []
    timestamps: list[str] = []
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [], [f"events.csv ilegível: {exc}"]
    if raw.startswith(b"\xef\xbb\xbf") or "\r" in text:
        errors.append("events.csv: codificação ou fim de linha fora do formato")
    if not text.endswith("\n"):
        errors.append("events.csv: deve terminar com newline")
    lines = text.split("\n")[:-1] if text.endswith("\n") else text.split("\n")
    if not lines or lines[0] != EVENTS_HEADER:
        errors.append("events.csv: cabeçalho inválido")
        return bits, timestamps, errors
    for expected_seq, line in enumerate(lines[1:], start=1):
        parts = line.split(",")
        if len(parts) != 4:
            errors.append(f"events.csv: linha {expected_seq} malformada")
            break
        event_id, seq, bit, ts = parts
        if seq != str(expected_seq):
            errors.append(f"events.csv: sequence_number não é contínuo/crescente na linha {expected_seq}")
            break
        if event_id != f"{session_id}-{expected_seq:06d}":
            errors.append(f"events.csv: event_id inconsistente na linha {expected_seq}")
            break
        if bit not in ("0", "1"):
            errors.append(f"events.csv: valor não binário na linha {expected_seq}")
            break
        bits.append(int(bit))
        timestamps.append(ts)
    return bits, timestamps, errors


def build_analysis(
    *,
    preregistration: dict,
    manifest: dict,
    bits: list[int],
    target: int,
    timeline: dict,
    hashes: dict,
    audit_head_hash: str,
    analyzed_timestamp: str,
) -> dict:
    n = len(bits)
    ones = sum(bits)
    zeros = n - ones
    hits = ones if target == 1 else zeros
    stats = binomial_analysis(
        n=n,
        hits=hits,
        alternative=Alternative(preregistration["alternative_hypothesis"]),
        alpha=preregistration["alpha"],
    )
    return {
        "session_id": preregistration["session_id"],
        "module": preregistration["module"],
        "test_mode": preregistration["test_mode"],
        "source_type": manifest["source_type"],
        "preregistration_sha256": hashes["preregistration_sha256"],
        "manifest_sha256": hashes["manifest_sha256"],
        "events_sha256": hashes["events_sha256"],
        "audit_head_hash": audit_head_hash,
        "target": target,
        "target_selection_method": preregistration["target_selection_method"],
        "target_selected_timestamp": timeline.get("target_selected_timestamp"),
        "intention_started_at": timeline.get("intention_started_at"),
        "intention_completed_at": timeline.get("intention_completed_at"),
        "participants_count": preregistration["participants_count"],
        "zeros": zeros,
        "ones": ones,
        "proportion_of_ones": ones / n,
        **stats,
        "analyzed_timestamp": analyzed_timestamp,
        "software_version": SOFTWARE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
    }


# Campos recalculáveis que precisam bater na verificação.
RECOMPUTED_FIELDS = (
    "n",
    "zeros",
    "ones",
    "hits",
    "target",
    "observed_proportion",
    "expected_proportion",
    "absolute_deviation",
    "deviation_pp",
    "z_score",
    "alternative_hypothesis",
    "alpha",
    "p_value",
    "ci_95",
    "significant",
    "result_statement",
    "proportion_of_ones",
    "participants_count",
    "preregistration_sha256",
    "manifest_sha256",
    "events_sha256",
)
