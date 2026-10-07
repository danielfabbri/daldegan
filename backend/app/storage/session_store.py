"""Arquivos da sessão em disco — a fonte da verdade (SPEC §2.3, §4.2).

Todos os arquivos de dados são write-once (abertos com modo "x"). O arquivo
qrng_raw.jsonl só aceita append enquanto events.csv e manifest.json não
existirem. Depois do selamento os arquivos recebem atributo somente leitura
como defesa adicional; a proteção principal é a máquina de estados.
"""

import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..audit.hashing import canonical_json
from ..errors import NotFound, SealedSessionError

SESSION_ID_RE = re.compile(r"^DAL(TEST)?-\d{4}-[0-9a-f]{8}$")

PREREGISTRATION = "preregistration.json"
MANIFEST = "manifest.json"
EVENTS = "events.csv"
QRNG_RAW = "qrng_raw.jsonl"
AUDIT = "audit.log"
ANALYSIS = "analysis.json"
REPORT = "report.html"

READ_ONLY_FILES = (PREREGISTRATION, MANIFEST, EVENTS, QRNG_RAW, ANALYSIS)


def validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not SESSION_ID_RE.fullmatch(session_id):
        raise NotFound(f"session_id inválido: {session_id!r}")
    return session_id


def is_test_session_id(session_id: str) -> bool:
    return session_id.startswith("DALTEST-")


@dataclass(frozen=True)
class SessionPaths:
    root: Path

    @property
    def preregistration(self) -> Path:
        return self.root / PREREGISTRATION

    @property
    def manifest(self) -> Path:
        return self.root / MANIFEST

    @property
    def events(self) -> Path:
        return self.root / EVENTS

    @property
    def qrng_raw(self) -> Path:
        return self.root / QRNG_RAW

    @property
    def audit(self) -> Path:
        return self.root / AUDIT

    @property
    def analysis(self) -> Path:
        return self.root / ANALYSIS

    @property
    def report(self) -> Path:
        return self.root / REPORT


class SessionStore:
    def __init__(self, sessions_dir: Path, test_sessions_dir: Path):
        self.sessions_dir = sessions_dir
        self.test_sessions_dir = test_sessions_dir

    def _base(self, test_mode: bool) -> Path:
        return self.test_sessions_dir if test_mode else self.sessions_dir

    def create_session_dir(self, test_mode: bool, now: datetime) -> tuple[str, str, SessionPaths]:
        """Cria um diretório novo. Nunca reutiliza nem sobrescreve um existente."""
        base = self._base(test_mode)
        base.mkdir(parents=True, exist_ok=True)
        prefix = "DALTEST" if test_mode else "DAL"
        for _ in range(100):
            session_uuid = str(uuid.uuid4())
            short = session_uuid.replace("-", "")[:8]
            session_id = f"{prefix}-{now.year:04d}-{short}"
            root = base / session_id
            try:
                root.mkdir()  # falha se já existir
            except FileExistsError:
                continue
            return session_id, session_uuid, SessionPaths(root)
        raise RuntimeError("não foi possível gerar um session_id único")

    def paths(self, session_id: str) -> SessionPaths:
        validate_session_id(session_id)
        return SessionPaths(self._base(is_test_session_id(session_id)) / session_id)

    # --- escrita write-once -------------------------------------------------

    @staticmethod
    def _write_once(path: Path, data: bytes) -> None:
        try:
            with open(path, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except FileExistsError as exc:
            raise SealedSessionError(f"{path.name} já existe e não pode ser sobrescrito") from exc

    def write_json_once(self, path: Path, obj: dict) -> bytes:
        data = canonical_json(obj)
        self._write_once(path, data)
        return data

    def write_bytes_once(self, path: Path, data: bytes) -> None:
        self._write_once(path, data)

    def ensure_raw_file(self, paths: SessionPaths) -> None:
        if paths.events.exists() or paths.manifest.exists():
            raise SealedSessionError("sessão selada: não é possível iniciar nova coleta")
        self._write_once(paths.qrng_raw, b"")

    def append_raw_block(self, paths: SessionPaths, block: dict) -> None:
        if paths.manifest.exists() or paths.events.exists():
            raise SealedSessionError("sessão selada: qrng_raw.jsonl não aceita novos blocos")
        with open(paths.qrng_raw, "ab") as f:
            f.write(canonical_json(block) + b"\n")
            f.flush()
            os.fsync(f.fileno())

    @staticmethod
    def make_read_only(paths: SessionPaths) -> None:
        for name in READ_ONLY_FILES:
            p = paths.root / name
            if p.exists():
                os.chmod(p, stat.S_IREAD)
