"""Tentativas de "roubo" (SPEC §15.2).

Cada adulteração precisa invalidar a sessão na revelação E fazer o
verificador externo responder INTEGRIDADE: FALHOU.
"""

import json
import sqlite3

import pytest

from backend.app.audit.audit_log import entry_hash
from backend.app.audit.hashing import canonical_json

from .conftest import make_writable, rewrite, run_completed, run_to_reveal_pending, run_verifier


def _flip_bit(data: bytes) -> bytes:
    lines = data.split(b"\n")
    parts = lines[10].split(b",")
    parts[2] = b"1" if parts[2] == b"0" else b"0"
    lines[10] = b",".join(parts)
    return b"\n".join(lines)


def _delete_event(data: bytes) -> bytes:
    lines = data.split(b"\n")
    del lines[-2]
    return b"\n".join(lines)


def _add_event(data: bytes) -> bytes:
    lines = data.split(b"\n")
    last = lines[-2].split(b",")
    seq = int(last[1]) + 1
    sid = last[0].rsplit(b"-", 1)[0]
    lines.insert(-1, b"%s-%06d,%d,1,%s" % (sid, seq, seq, last[3]))
    return b"\n".join(lines)


def _flip_raw_byte(data: bytes) -> bytes:
    lines = data.split(b"\n")
    block = json.loads(lines[0])
    body = json.loads(block["body"])
    body["data"][0] ^= 0xFF
    block["body"] = json.dumps(body)
    lines[0] = canonical_json(block)
    return b"\n".join(lines)


def _edit_json(path, **changes):
    def transform(data: bytes) -> bytes:
        obj = json.loads(data)
        obj.update(changes)
        return canonical_json(obj)

    rewrite(path, transform)


def _rechained_audit(path, mutate):
    """Edita o audit.log E recalcula toda a cadeia (adversário sofisticado)."""
    entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    mutate(entries)
    prev = "0" * 64
    for i, e in enumerate(entries, start=1):
        e["seq"] = i
        e["hash_previous_log_entry"] = prev
        e["hash_current_log_entry"] = entry_hash(e)
        prev = e["hash_current_log_entry"]
    make_writable(path)
    path.write_bytes(b"".join(canonical_json(e) + b"\n" for e in entries))


def _set_target_in_audit(entries):
    for e in entries:
        if e["event"] == "TARGET_SELECTED":
            e["metadata"]["target"] = 1 - e["metadata"]["target"]


def _shorten_intention(entries):
    for e in entries:
        if e["event"] == "INTENTION_COMPLETED":
            e["timestamp"] = e["timestamp"].replace("12:01:01", "12:00:30")


def _move_target_before_seal(entries):
    idx = next(i for i, e in enumerate(entries) if e["event"] == "TARGET_SELECTED")
    seal = next(i for i, e in enumerate(entries) if e["event"] == "DATA_SEALED")
    entries.insert(seal, entries.pop(idx))


def _remove_line(path):
    lines = path.read_bytes().split(b"\n")
    del lines[3]
    make_writable(path)
    path.write_bytes(b"\n".join(lines))


def _db(service, sql, *args):
    conn = sqlite3.connect(service.settings.index_db_path)
    conn.execute(sql, args)
    conn.commit()
    conn.close()


TAMPERS = {
    "alterar_um_bit": lambda svc, p: rewrite(p.events, _flip_bit),
    "apagar_um_evento": lambda svc, p: rewrite(p.events, _delete_event),
    "adicionar_um_evento": lambda svc, p: rewrite(p.events, _add_event),
    "alterar_bruto_qrng": lambda svc, p: rewrite(p.qrng_raw, _flip_raw_byte),
    "alterar_alvo_no_indice": lambda svc, p: _db(svc, "UPDATE sessions SET target = 1 - target"),
    "alterar_alvo_no_audit_log": lambda svc, p: _rechained_audit(p.audit, _set_target_in_audit),
    "alterar_participantes_preregistro": lambda svc, p: _edit_json(p.preregistration, participants_count=7),
    "alterar_participantes_indice": lambda svc, p: _db(svc, "UPDATE sessions SET participants_count = 7"),
    "alterar_duracao_preregistro": lambda svc, p: _edit_json(p.preregistration, planned_duration_seconds=10),
    "alterar_duracao_indice": lambda svc, p: _db(svc, "UPDATE sessions SET planned_duration_seconds = 10"),
    "alterar_teste_estatistico": lambda svc, p: _edit_json(p.preregistration, alternative_hypothesis="GREATER"),
    "alterar_alpha": lambda svc, p: _edit_json(p.preregistration, alpha=0.1),
    "alterar_manifesto": lambda svc, p: _edit_json(p.manifest, event_count=999),
    "alterar_audit_log_sem_recalcular": lambda svc, p: rewrite(p.audit, lambda b: b.replace(b"GENERATION_STARTED", b"GENERATION_STARTEX", 1)),
    "remover_linha_do_audit_log": lambda svc, p: _remove_line(p.audit),
    "encurtar_intencao_no_audit_log": lambda svc, p: _rechained_audit(p.audit, _shorten_intention),
    "alvo_antes_do_selamento": lambda svc, p: _rechained_audit(p.audit, _move_target_before_seal),
    "apagar_events_csv": lambda svc, p: (make_writable(p.events), p.events.unlink()),
}

# Adulterações que só existem no índice: o verificador externo não lê o SQLite.
INDEX_ONLY = {"alterar_alvo_no_indice", "alterar_participantes_indice", "alterar_duracao_indice"}
# Reescrita completa e coerente da cadeia: só detectável pelo verificador com âncora externa.
FULL_RECHAIN = {"alterar_alvo_no_audit_log"}


def _target_entry_hash(paths) -> str:
    for line in paths.audit.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event"] == "TARGET_SELECTED":
            return e["hash_current_log_entry"]
    raise AssertionError("TARGET_SELECTED ausente")


@pytest.mark.parametrize("name", sorted(TAMPERS))
async def test_tampering_invalidates_session(service, clock, name):
    sid = await run_to_reveal_pending(service, clock, "MODULE_2", target=0)
    paths = service.paths(sid)
    anchor = _target_entry_hash(paths)  # código que a interface mostra após a escolha do alvo
    TAMPERS[name](service, paths)

    out = service.reveal(sid)
    assert out["valid"] is False, name
    assert service.get_record(sid)["state"] == "INVALIDATED"
    assert not paths.analysis.exists()

    if name in INDEX_ONLY:
        return
    if name in FULL_RECHAIN:
        # Limitação documentada: sem âncora externa, uma cadeia reescrita por inteiro é coerente.
        assert run_verifier(paths.root).returncode == 0
        proc = run_verifier(paths.root, anchor)
    else:
        proc = run_verifier(paths.root)
    assert proc.returncode == 1, proc.stdout
    assert json.loads(proc.stdout)["verdict"] == "INTEGRIDADE: FALHOU"


@pytest.mark.parametrize("field,value", [("p_value", 0.0001), ("significant", True), ("hits", 1), ("ones", 1)])
async def test_altering_statistics_after_reveal_is_detected(service, clock, field, value):
    sid = await run_completed(service, clock)
    paths = service.paths(sid)
    _edit_json(paths.analysis, **{field: value})
    assert not service.verify(sid).ok
    assert service.get_record(sid)["integrity_status"] == "FAILED"
    proc = run_verifier(paths.root)
    assert proc.returncode == 1


async def test_altering_statistics_with_matching_audit_hash_is_still_detected(service, clock):
    """Mesmo recalculando o hash do analysis.json no audit log, a estatística recalculada diverge."""
    from backend.app.audit.hashing import sha256_bytes

    sid = await run_completed(service, clock)
    paths = service.paths(sid)
    _edit_json(paths.analysis, p_value=0.0001, significant=True)
    new_sha = sha256_bytes(paths.analysis.read_bytes())

    def mutate(entries):
        for e in entries:
            if e["event"] == "ANALYSIS_COMPLETED":
                e["metadata"]["analysis_sha256"] = new_sha

    _rechained_audit(paths.audit, mutate)
    assert not service.verify(sid).ok
    assert run_verifier(paths.root).returncode == 1


async def test_reveal_on_broken_chain_is_recorded_in_global_log(service, clock):
    from backend.app.audit.audit_log import read_entries

    sid = await run_to_reveal_pending(service, clock)
    _remove_line(service.paths(sid).audit)
    assert service.reveal(sid)["valid"] is False
    assert service.get_record(sid)["state"] == "INVALIDATED"
    events = [(e["session_id"], e["event"]) for e in read_entries(service.settings.global_audit_path)]
    assert (sid, "SESSION_INVALIDATED") in events
