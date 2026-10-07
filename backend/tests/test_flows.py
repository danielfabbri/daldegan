"""Fluxos de serviço: falha da fonte, fonte quântica, alvo sorteado, cegamento,
análise acumulada e recuperação após reinício."""

import json

import httpx
import pytest

from backend.app.errors import IllegalTransition, SourceUnavailable
from backend.app.models.api import SelectTargetRequest
from backend.app.qrng.anu import QuantumRandomSource
from backend.app.services import blind_view, history_service
from backend.app.services.session_service import SessionService

from .conftest import make_request, run_completed, run_to_reveal_pending, run_verifier

FORBIDDEN_BLIND_KEYS = {"zeros", "ones", "hits", "bits", "proportion_of_ones"}


def _quantum_factory(fail_at=None):
    def handler(request):
        handler.calls += 1
        if fail_at is not None and handler.calls > fail_at:
            return httpx.Response(503, text="Service Unavailable")
        n = int(request.url.params["length"])
        return httpx.Response(200, json={"type": "uint8", "length": n,
                                         "data": [(handler.calls * 31 + k) % 256 for k in range(n)],
                                         "success": True})

    handler.calls = 0
    return lambda: QuantumRandomSource(api_key="k", endpoint="https://api.example", min_interval_s=0,
                                       transport=httpx.MockTransport(handler))


async def test_experimental_session_uses_quantum_source(service, clock, factory):
    factory.quantum = _quantum_factory()
    sid = await run_completed(service, clock, "MODULE_2", test_mode=False)
    assert sid.startswith("DAL-")
    manifest = json.loads(service.paths(sid).manifest.read_text(encoding="utf-8"))
    assert manifest["source_type"] == "QUANTUM"
    assert manifest["source_endpoint"] == "https://api.example"
    assert manifest["number_of_bits_requested"] == manifest["number_of_bits_received"] == 1000
    assert run_verifier(service.paths(sid).root).returncode == 0


async def test_quantum_unavailable_never_creates_pseudorandom_session(service, factory):
    factory.quantum = None
    with pytest.raises(SourceUnavailable):
        await service.create_session(make_request("MODULE_2", test_mode=False))
    assert service.index.list_sessions() == []


async def test_qrng_failure_mid_generation_preserves_partial_data(service, factory):
    factory.quantum = _quantum_factory(fail_at=1)
    rec = await service.create_session(make_request("MODULE_2", event_count=20_000, test_mode=False))
    sid = rec["session_id"]
    await service.generate(sid)
    record = service.get_record(sid)
    assert record["state"] == "QRNG_ERROR"
    paths = service.paths(sid)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert manifest["partial"] is True
    assert manifest["number_of_bits_received"] == 8192  # um bloco de 1024 bytes
    assert manifest["source_type"] == "QUANTUM"
    lines = paths.events.read_text(encoding="utf-8").splitlines()
    assert len(lines) - 1 == 8192  # nunca completado
    assert len(paths.qrng_raw.read_text(encoding="utf-8").splitlines()) == 1
    with pytest.raises(IllegalTransition):
        service.begin_generation(sid)  # não há nova tentativa na mesma sessão
    # verificador externo aponta a coleta parcial
    assert run_verifier(paths.root).returncode == 1


async def test_test_mode_session_is_marked_and_separated(service, clock):
    sid = await run_completed(service, clock, "MODULE_2", test_mode=True)
    assert sid.startswith("DALTEST-")
    assert service.paths(sid).root.parent == service.settings.test_sessions_dir
    prereg = json.loads(service.paths(sid).preregistration.read_text(encoding="utf-8"))
    assert prereg["random_source"]["source_type"] == "PSEUDORANDOM_TEST"
    assert history_service.history(service, test_mode=False)["sessions"] == []
    assert len(history_service.history(service, test_mode=True)["sessions"]) == 1
    with pytest.raises(IllegalTransition):
        history_service.cumulative(service, "MANUAL", None, [sid])


async def test_module1_preregisters_target_before_generation(service, clock):
    rec = await service.create_session(make_request("MODULE_1", target=0))
    sid = rec["session_id"]
    prereg = json.loads(service.paths(sid).preregistration.read_text(encoding="utf-8"))
    assert prereg["planned_target"] == 0
    assert rec["state"] == "TARGET_SELECTED"
    assert not service.paths(sid).events.exists()
    with pytest.raises(IllegalTransition):
        service.begin_generation(sid)  # geração antes da intenção é proibida
    service.start_intention(sid)
    with pytest.raises(IllegalTransition):
        service.begin_generation(sid)
    clock.advance(61)
    service.complete_intention(sid)
    await service.run_generation(sid)
    assert service.get_record(sid)["state"] == "REVEAL_PENDING"


async def test_module1_system_randomized_target(service, clock):
    rec = await service.create_session(make_request("MODULE_1", target=None, target_selection_method="SYSTEM_QUANTUM"))
    prereg = json.loads(service.paths(rec["session_id"]).preregistration.read_text(encoding="utf-8"))
    assert prereg["planned_target"] in (0, 1)
    assert prereg["target_selection_method"] == "SYSTEM_QUANTUM"
    events = [e["event"] for e in service._audit(rec["session_id"]).entries()]
    assert events.index("TARGET_RANDOMIZED") < events.index("PREREGISTERED")


async def test_module2_preregistration_has_null_target(service):
    rec = await service.create_session(make_request("MODULE_2"))
    prereg = json.loads(service.paths(rec["session_id"]).preregistration.read_text(encoding="utf-8"))
    assert prereg["planned_target"] is None


async def test_module2_target_method_is_fixed_by_preregistration(service):
    rec = await service.create_session(make_request("MODULE_2", target_selection_method="SYSTEM_QUANTUM"))
    sid = rec["session_id"]
    await service.generate(sid)
    with pytest.raises(IllegalTransition):
        await service.select_target(sid, SelectTargetRequest(target=1))
    rec = await service.select_target(sid, SelectTargetRequest())
    assert rec["target"] in (0, 1)
    with pytest.raises(IllegalTransition):
        await service.select_target(sid, SelectTargetRequest())  # alvo não pode ser trocado


async def test_control_sham_target_is_hidden_until_reveal(service, clock):
    rec = await service.create_session(make_request("CONTROL"))
    sid = rec["session_id"]
    await service.generate(sid)
    record = service.get_record(sid)
    assert record["state"] == "TARGET_SELECTED"
    assert record["target"] in (0, 1)
    assert blind_view.serialize(record, clock)["target"] is None
    service.start_intention(sid)
    clock.advance(61)
    service.complete_intention(sid)
    assert blind_view.serialize(service.get_record(sid), clock)["target"] is None
    service.reveal(sid)
    assert blind_view.serialize(service.get_record(sid), clock)["target"] == record["target"]


async def test_blind_view_never_exposes_data_before_reveal(service, clock):
    rec = await service.create_session(make_request("MODULE_2"))
    sid = rec["session_id"]
    snapshots = [service.get_record(sid)]
    await service.generate(sid)
    snapshots.append(service.get_record(sid))
    await service.select_target(sid, SelectTargetRequest(target=1))
    service.start_intention(sid)
    snapshots.append(service.get_record(sid))
    clock.advance(61)
    service.complete_intention(sid)
    snapshots.append(service.get_record(sid))
    for record in snapshots:
        view = blind_view.serialize(record, clock)
        assert not FORBIDDEN_BLIND_KEYS & set(view)
        assert view["observed_proportion"] is None and view["p_value"] is None and view["significant"] is None
        assert view["result_available"] is False


async def test_participants_count_does_not_change_statistics(service, clock, factory):
    factory.seed = 100
    a = await run_completed(service, clock, "MODULE_2", participants_count=1)
    factory.seed = 100  # mesma sequência de dados para a segunda sessão
    b = await run_completed(service, clock, "MODULE_2", participants_count=50)
    ra, rb = service.read_analysis(a), service.read_analysis(b)
    assert ra["participants_count"] == 1 and rb["participants_count"] == 50
    for key in ("n", "hits", "p_value", "ci_95", "z_score", "observed_proportion"):
        assert ra[key] == rb[key]


async def test_cumulative_protocol_mode_includes_all_completed_sessions(service, clock, factory):
    factory.quantum = _quantum_factory()
    ids = [await run_completed(service, clock, "MODULE_2", test_mode=False) for _ in range(3)]
    invalid = await run_to_reveal_pending(service, clock, "MODULE_2", test_mode=False)
    from .conftest import rewrite

    rewrite(service.paths(invalid).events, lambda b: b.replace(b",0,", b",1,", 1))
    service.reveal(invalid)
    fp = service.get_record(ids[0])["protocol_fingerprint"]

    out = history_service.cumulative(service, "PROTOCOL", fp, None)
    assert out["exploratory"] is False
    included = [r for r in out["sessions"] if r["included"]]
    assert sorted(r["session_id"] for r in included) == sorted(ids)
    excluded = [r for r in out["sessions"] if not r["included"]]
    assert [r["session_id"] for r in excluded] == [invalid]  # listada, não escondida
    total = sum(service.read_analysis(s)["n"] for s in ids)
    assert out["combined"]["total_events"] == total
    assert out["combined"]["total_zeros"] + out["combined"]["total_ones"] == total

    protocols = history_service.list_protocols(service)
    assert protocols[0]["sessions"] == 4

    manual = history_service.cumulative(service, "MANUAL", None, ids[:2])
    assert manual["exploratory"] is True
    assert manual["warning"] == "Esta análise é exploratória e está sujeita a viés de seleção."


async def test_different_protocols_are_not_mixed(service, clock, factory):
    factory.quantum = _quantum_factory()
    a = await run_completed(service, clock, "MODULE_2", test_mode=False, event_count=1000)
    b = await run_completed(service, clock, "MODULE_2", test_mode=False, event_count=2000)
    fa = service.get_record(a)["protocol_fingerprint"]
    assert fa != service.get_record(b)["protocol_fingerprint"]
    out = history_service.cumulative(service, "PROTOCOL", fa, None)
    assert [r["session_id"] for r in out["sessions"]] == [a]


async def test_restart_during_generation_marks_qrng_error(settings, clock, factory):
    svc = SessionService(settings, clock, factory)
    rec = await svc.create_session(make_request("MODULE_2"))
    svc.begin_generation(rec["session_id"])  # servidor "cai" antes de coletar
    svc.index.close()

    restarted = SessionService(settings, clock, factory)
    assert restarted.recover_interrupted() == [rec["session_id"]]
    record = restarted.get_record(rec["session_id"])
    assert record["state"] == "QRNG_ERROR"
    assert "interrompida" in record["invalid_reason"]
    restarted.index.close()


async def test_removed_session_directory_is_reported_in_history(service, clock):
    import shutil

    from .conftest import make_writable

    sid = await run_completed(service, clock)
    root = service.paths(sid).root
    for p in root.iterdir():
        make_writable(p)
    shutil.rmtree(root)
    rows = history_service.history(service, test_mode=True)["sessions"]
    assert rows[0]["integrity_label"] == "AUSENTE"
