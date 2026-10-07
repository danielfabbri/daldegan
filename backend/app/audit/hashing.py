"""Serialização canônica e SHA-256 (SPEC §4.3).

Todo JSON gravado em disco é exatamente canonical_json(obj): chaves ordenadas,
sem espaços, UTF-8, sem newline final. Assim o hash do arquivo é igual ao hash
do objeto.
"""

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

FLOAT_DECIMALS = 12
GENESIS_HASH = "0" * 64


def round_floats(obj):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ValueError("NaN/Inf não são permitidos em JSON canônico")
        return round(obj, FLOAT_DECIMALS)
    if isinstance(obj, dict):
        return {k: round_floats(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [round_floats(v) for v in obj]
    return obj


def canonical_json(obj) -> bytes:
    return json.dumps(
        round_floats(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC com microssegundos e sufixo Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
