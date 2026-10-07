import os
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.clock import FakeClock
from backend.app.config import Settings
from backend.app.errors import SourceUnavailable
from backend.app.main import create_app
from backend.app.models.api import CreateSessionRequest, SelectTargetRequest
from backend.app.models.enums import SourceType
from backend.app.qrng.local import LocalRandomSource
from backend.app.services.session_service import SessionService

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts" / "verify_session.py"


class FakeSourceFactory:
    """Fábrica de testes: fonte local com seed. A fonte "quântica" é configurável
    por teste (por padrão indisponível, como em uma máquina sem API key)."""

    def __init__(self):
        self.seed = 12345
        self.quantum = None  # callable sem argumentos que devolve uma fonte QUANTUM
        self.local_kwargs = {}

    def __call__(self, source_type: SourceType):
        if source_type == SourceType.PSEUDORANDOM_TEST:
            self.seed += 1
            return LocalRandomSource(seed=self.seed, **self.local_kwargs)
        if self.quantum is None:
            raise SourceUnavailable("fonte quântica não configurada (teste)")
        return self.quantum()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data", qrng_api_key=None, qrng_min_interval_s=0, _env_file=None)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def factory() -> FakeSourceFactory:
    return FakeSourceFactory()


@pytest.fixture
def service(settings, clock, factory) -> SessionService:
    svc = SessionService(settings, clock, factory)
    yield svc
    svc.index.close()


@pytest.fixture
def client(settings, clock, factory):
    app = create_app(settings=settings, clock=clock, source_factory=factory)
    with TestClient(app) as c:
        c.clock = clock
        c.factory = factory
        c.service = app.state.service
        yield c


def make_request(module="MODULE_2", **overrides) -> CreateSessionRequest:
    kw = dict(module=module, event_count=1000, participants_count=3, duration_seconds=60, test_mode=True)
    if module == "MODULE_1":
        kw["target"] = 1
    kw.update(overrides)
    return CreateSessionRequest(**kw)


async def run_to_reveal_pending(svc: SessionService, clock: FakeClock, module="MODULE_2", target=1, **overrides) -> str:
    rec = await svc.create_session(make_request(module, **overrides))
    sid = rec["session_id"]
    if module != "MODULE_1":
        await svc.generate(sid)
        if module == "MODULE_2":
            await svc.select_target(sid, SelectTargetRequest(target=target))
    svc.start_intention(sid)
    clock.advance(svc.get_record(sid)["planned_duration_seconds"] + 1)
    svc.complete_intention(sid)
    if module == "MODULE_1":
        await svc.run_generation(sid)
    assert svc.get_record(sid)["state"] == "REVEAL_PENDING"
    return sid


async def run_completed(svc: SessionService, clock: FakeClock, module="MODULE_2", **kw) -> str:
    sid = await run_to_reveal_pending(svc, clock, module, **kw)
    out = svc.reveal(sid)
    assert out["valid"], out["integrity"]
    return sid


def make_writable(path: Path) -> None:
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def rewrite(path: Path, transform) -> None:
    """Simula adulteração manual de um arquivo (ignora o atributo somente leitura)."""
    make_writable(path)
    path.write_bytes(transform(path.read_bytes()))


def run_verifier(session_dir: Path, *anchors: str):
    import subprocess

    args = [a for h in anchors for a in ("--anchor", h)]
    return subprocess.run(
        [sys.executable, str(VERIFIER), str(session_dir), "--json", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
