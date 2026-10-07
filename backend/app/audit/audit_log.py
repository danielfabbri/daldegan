"""audit.log append-only com cadeia de hashes (SPEC §4.7).

Formato: JSON Lines. Cada linha é canonical_json da entrada.
hash_current_log_entry = sha256(canonical_json(entrada sem hash_current_log_entry)).
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .hashing import GENESIS_HASH, canonical_json, format_ts, sha256_bytes

ENTRY_FIELDS = (
    "seq",
    "timestamp",
    "session_id",
    "event",
    "metadata",
    "hash_previous_log_entry",
    "hash_current_log_entry",
)


def entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash_current_log_entry"}
    return sha256_bytes(canonical_json(body))


@dataclass
class ChainReport:
    ok: bool
    entries: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def head_hash(self) -> str:
        return self.entries[-1]["hash_current_log_entry"] if self.entries else GENESIS_HASH


def read_entries(path: Path) -> list[dict]:
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        for line in f:
            line = line.rstrip("\n")
            if line:
                entries.append(json.loads(line))
    return entries


def verify_chain(path: Path) -> ChainReport:
    if not path.exists():
        return ChainReport(ok=False, errors=["audit.log ausente"])
    try:
        entries = read_entries(path)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return ChainReport(ok=False, errors=[f"linha ilegível no audit.log: {exc}"])

    errors: list[str] = []
    previous = GENESIS_HASH
    for i, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict) or set(entry) != set(ENTRY_FIELDS):
            errors.append(f"entrada {i}: campos inesperados")
            break
        if entry["seq"] != i:
            errors.append(f"entrada {i}: seq={entry['seq']} fora de ordem")
            break
        if entry["hash_previous_log_entry"] != previous:
            errors.append(f"entrada {i}: hash_previous_log_entry não confere")
            break
        if entry_hash(entry) != entry["hash_current_log_entry"]:
            errors.append(f"entrada {i}: hash_current_log_entry não confere")
            break
        previous = entry["hash_current_log_entry"]
    if not entries:
        errors.append("audit.log vazio")
    return ChainReport(ok=not errors, entries=entries, errors=errors)


class AuditLog:
    """Log encadeado. Só existe a operação append."""

    def __init__(self, path: Path):
        self.path = path

    def append(self, session_id: str, event: str, timestamp: datetime, metadata: dict | None = None) -> dict:
        entries = read_entries(self.path)
        previous = entries[-1]["hash_current_log_entry"] if entries else GENESIS_HASH
        entry = {
            "seq": len(entries) + 1,
            "timestamp": format_ts(timestamp),
            "session_id": session_id,
            "event": event,
            "metadata": metadata or {},
            "hash_previous_log_entry": previous,
        }
        entry["hash_current_log_entry"] = entry_hash(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "ab") as f:
            f.write(canonical_json(entry) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        return entry

    def entries(self) -> list[dict]:
        return read_entries(self.path)
