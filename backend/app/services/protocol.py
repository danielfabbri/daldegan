"""Pré-registro e fingerprint de protocolo (SPEC §4.4, §7.5)."""

from ..audit.hashing import canonical_json, sha256_bytes

FINGERPRINT_FIELDS = (
    "module",
    "test_mode",
    "planned_event_count",
    "planned_duration_seconds",
    "target_selection_method",
    "statistical_test",
    "alternative_hypothesis",
    "alpha",
    "protocol_version",
)


def protocol_fingerprint(preregistration: dict) -> str:
    return sha256_bytes(canonical_json({k: preregistration[k] for k in FINGERPRINT_FIELDS}))


def protocol_description(preregistration: dict) -> dict:
    return {k: preregistration[k] for k in FINGERPRINT_FIELDS}
