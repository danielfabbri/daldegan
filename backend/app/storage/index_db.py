"""Índice SQLite das sessões (SPEC §4.9).

É apenas um índice para listagem e estado de execução; os arquivos da sessão
prevalecem. Proporção e p-value só são gravados a partir de REVEALED.
"""

import sqlite3
import threading
from pathlib import Path

COLUMNS = (
    "session_id",
    "session_uuid",
    "module",
    "test_mode",
    "state",
    "created_at",
    "planned_event_count",
    "planned_duration_seconds",
    "participants_count",
    "target",
    "target_selection_method",
    "alternative_hypothesis",
    "alpha",
    "protocol_fingerprint",
    "preregistration_sha256",
    "events_sha256",
    "manifest_sha256",
    "target_selected_at",
    "intention_started_at",
    "intention_ends_at",
    "intention_completed_at",
    "bits_requested",
    "bits_received",
    "observed_proportion",
    "p_value",
    "significant",
    "integrity_status",
    "invalid_reason",
    "dir_path",
    "updated_at",
)

_SCHEMA = "CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, " + ", ".join(COLUMNS[1:]) + ")"


class IndexDB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def insert(self, record: dict) -> None:
        cols = [c for c in COLUMNS if c in record]
        sql = f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})"
        with self._lock:
            self._conn.execute(sql, [record[c] for c in cols])

    def update(self, session_id: str, **fields) -> None:
        unknown = set(fields) - set(COLUMNS)
        if unknown:
            raise KeyError(f"colunas desconhecidas: {unknown}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE sessions SET {sets} WHERE session_id = ?", [*fields.values(), session_id])

    def get(self, session_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM sessions WHERE session_id = ?", [session_id]).fetchone()
        return dict(row) if row else None

    def list_sessions(self, test_mode: bool | None = None) -> list[dict]:
        sql = "SELECT * FROM sessions"
        args: list = []
        if test_mode is not None:
            sql += " WHERE test_mode = ?"
            args.append(int(test_mode))
        sql += " ORDER BY created_at DESC"
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def by_state(self, state: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM sessions WHERE state = ?", [state]).fetchall()
        return [dict(r) for r in rows]
