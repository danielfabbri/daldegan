"""Testes de integridade exigidos pela SPEC §15.1."""

import json

import pytest

from backend.app.errors import Blinded, IllegalTransition, SealedSessionError, TooEarly
from backend.app.services import history_service
from backend.app.services.analysis_builder import parse_events_csv
from backend.app.services.integrity import verify_session

from .conftest import make_request, rewrite, run_completed, run_to_reveal_pending, run_verifier


async def test_cannot_reveal_before_intention(service, clock):
    rec = await service.create_session(make_request("MODULE_2"))
    sid = rec["session_id"]
    with pytest.raises(IllegalTransition):
        service.reveal(sid)  # PRE_REGISTERED
    await service.generate(sid)
    with pytest.raises(IllegalTransition):
        service.reveal(sid)  # SEALED
    from backend.app.models.api import SelectTargetRequest

    await service.select_target(sid, SelectTargetRequest(target=0))
    service.start_intention(sid)
    with pytest.raises(IllegalTransition):
        service.reveal(sid)  # INTENTION_RUNNING
    clock.advance(30)  # metade do período
    with pytest.raises(TooEarly):
        service.complete_intention(sid)
    with pytest.raises(IllegalTransition):
        service.reveal(sid)
    clock.advance(31)
    service.complete_intention(sid)
    assert service.reveal(sid)["valid"]


async def test_cannot_read_results_before_reveal(service, clock):
    sid = await run_to_reveal_pending(service, clock)
    for fn in (history_service.result, history_service.events_csv, history_service.export_json,
               history_service.report_html):
        with pytest.raises(Blinded):
            fn(service, sid)
    record = service.get_record(sid)
    assert record["observed_proportion"] is None and record["p_value"] is None
    assert not service.paths(sid).analysis.exists()


async def test_cannot_modify_sealed_events(service, clock):
    sid = await run_to_reveal_pending(service, clock)
    paths = service.paths(sid)
    with pytest.raises(SealedSessionError):
        service.store.write_bytes_once(paths.events, b"event_id,sequence_number,bit,timestamp_utc\n")
    with pytest.raises(SealedSessionError):
        service.store.append_raw_block(paths, {"index": 99})
    with pytest.raises(SealedSessionError):
        service.store.write_json_once(paths.manifest, {})
    with pytest.raises(IllegalTransition):
        await service.generate(sid)  # não existe regeneração
    # defesa adicional: arquivo somente leitura no sistema operacional
    with pytest.raises(PermissionError):
        open(paths.events, "ab").close()


async def test_event_count_matches_manifest(service, clock):
    sid = await run_to_reveal_pending(service, clock, event_count=777)
    paths = service.paths(sid)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    bits, _, errors = parse_events_csv(paths.events, sid)
    assert not errors
    assert len(bits) == manifest["event_count"] == manifest["number_of_bits_received"] == 777


async def test_events_are_binary(service, clock):
    sid = await run_to_reveal_pending(service, clock)
    bits, _, _ = parse_events_csv(service.paths(sid).events, sid)
    assert set(bits) <= {0, 1}
    def set_bit_to_2(data: bytes) -> bytes:
        lines = data.split(b"\n")
        parts = lines[3].split(b",")
        parts[2] = b"2"
        lines[3] = b",".join(parts)
        return b"\n".join(lines)

    rewrite(service.paths(sid).events, set_bit_to_2)
    _, _, errors = parse_events_csv(service.paths(sid).events, sid)
    assert any("binário" in e for e in errors)


async def test_event_sequence_is_monotonic(service, clock):
    sid = await run_to_reveal_pending(service, clock)
    lines = service.paths(sid).events.read_text(encoding="utf-8").splitlines()[1:]
    seqs = [int(line.split(",")[1]) for line in lines]
    assert seqs == list(range(1, len(lines) + 1))


async def test_audit_chain_of_real_session_is_valid(service, clock):
    from backend.app.audit.audit_log import verify_chain

    sid = await run_completed(service, clock)
    assert verify_chain(service.paths(sid).audit).ok


@pytest.mark.parametrize("module", ["MODULE_1", "MODULE_2", "CONTROL"])
async def test_external_verifier_matches_application(service, clock, module):
    sid = await run_completed(service, clock, module)
    paths = service.paths(sid)
    app_report = verify_session(paths, service.get_record(sid))
    proc = run_verifier(paths.root)
    out = json.loads(proc.stdout)
    assert app_report.ok is True
    assert out["ok"] is True and proc.returncode == 0
    assert out["verdict"] == "INTEGRIDADE: OK"

    # Depois de uma adulteração, ambos devem discordar da sessão da mesma forma.
    rewrite(paths.events, lambda b: b[:-3] + (b"0" if b[-3:-2] == b"1" else b"1") + b[-2:])
    assert not verify_session(paths, service.get_record(sid)).ok
    proc = run_verifier(paths.root)
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["verdict"] == "INTEGRIDADE: FALHOU"


async def test_invalid_session_is_rejected(service, clock):
    sid = await run_to_reveal_pending(service, clock)
    paths = service.paths(sid)
    lines = paths.events.read_bytes().split(b"\n")
    parts = lines[5].split(b",")
    parts[2] = b"1" if parts[2] == b"0" else b"0"
    lines[5] = b",".join(parts)
    rewrite(paths.events, lambda _: b"\n".join(lines))

    out = service.reveal(sid)
    assert out["valid"] is False
    record = service.get_record(sid)
    assert record["state"] == "INVALIDATED"
    assert record["observed_proportion"] is None
    assert not paths.analysis.exists()
    res = history_service.result(service, sid)
    assert res["valid"] is False
    assert res["message"] == "SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada."
    assert "analysis" not in res
    html = history_service.report_html(service, sid)
    assert "SESSÃO INVALIDADA" in html and "p-value" not in html
