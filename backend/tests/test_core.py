"""Hash canônico, máquina de estados e audit log."""

import itertools

import pytest

from backend.app.audit.audit_log import AuditLog, verify_chain
from backend.app.audit.hashing import canonical_json, sha256_bytes
from backend.app.clock import FakeClock
from backend.app.errors import IllegalTransition
from backend.app.models.enums import TERMINAL_STATES, Module, State
from backend.app.services.analysis_builder import build_events_csv
from backend.app.state_machine import TRANSITIONS, allowed_targets, check_transition

# ----------------------------------------------------------------- hashing


def test_hash_changes_when_event_changes():
    ts = ["2026-10-07T12:00:00.000000Z"] * 4
    a = build_events_csv("DAL-2026-00000000", [0, 1, 1, 0], ts)
    b = build_events_csv("DAL-2026-00000000", [0, 1, 0, 0], ts)
    assert sha256_bytes(a) != sha256_bytes(b)


def test_hash_changes_when_manifest_changes():
    m = {"session_id": "DAL-2026-00000000", "event_count": 1000, "events_sha256": "a" * 64}
    changed = dict(m, event_count=1001)
    assert sha256_bytes(canonical_json(m)) != sha256_bytes(canonical_json(changed))


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [1, 2.5]}) == canonical_json({"a": [1, 2.5], "b": 1})
    assert canonical_json({"a": "ç"}) == '{"a":"ç"}'.encode("utf-8")


# ----------------------------------------------------------- state machine

ALL_STATES = list(State)


@pytest.mark.parametrize("module", list(Module))
def test_only_table_transitions_are_allowed(module):
    table = TRANSITIONS[module]
    for current, target in itertools.product(ALL_STATES, ALL_STATES):
        allowed = target in table.get(current, set()) or (
            target == State.INVALIDATED and current not in TERMINAL_STATES
        )
        if allowed:
            check_transition(module, current, target)
        else:
            with pytest.raises(IllegalTransition):
                check_transition(module, current, target)


@pytest.mark.parametrize("module", list(Module))
def test_terminal_states_have_no_exit(module):
    for state in TERMINAL_STATES:
        assert allowed_targets(module, state) == set()


def test_module1_intention_precedes_generation_and_module2_follows_it():
    m1, m2 = TRANSITIONS[Module.MODULE_1], TRANSITIONS[Module.MODULE_2]
    assert State.GENERATING in m1[State.INTENTION_RUNNING]
    assert State.GENERATING not in m1[State.PRE_REGISTERED]
    assert State.GENERATING in m2[State.PRE_REGISTERED]
    assert State.TARGET_SELECTED in m2[State.SEALED]
    # não há caminho de volta para GENERATING depois do selamento
    for table in (m1, m2):
        for state in (State.SEALED, State.REVEAL_PENDING, State.REVEALED):
            assert State.GENERATING not in table.get(state, set())


# --------------------------------------------------------------- audit log


def _log(tmp_path, n=5):
    clock = FakeClock()
    log = AuditLog(tmp_path / "audit.log")
    for i in range(n):
        log.append("DAL-2026-00000000", f"EVENT_{i}", clock.now(), {"i": i})
        clock.advance(1)
    return log


def test_audit_chain_is_valid(tmp_path):
    log = _log(tmp_path)
    report = verify_chain(log.path)
    assert report.ok, report.errors
    assert len(report.entries) == 5
    assert report.entries[0]["hash_previous_log_entry"] == "0" * 64
    for prev, cur in zip(report.entries, report.entries[1:]):
        assert cur["hash_previous_log_entry"] == prev["hash_current_log_entry"]


def _lines(path):
    return path.read_bytes().split(b"\n")[:-1]


def _write(path, lines):
    path.write_bytes(b"\n".join(lines) + b"\n")


@pytest.mark.parametrize("tamper", ["edit", "remove_middle", "remove_last_keeps_valid_prefix", "reorder", "insert"])
def test_audit_chain_detects_tampering(tmp_path, tamper):
    log = _log(tmp_path)
    lines = _lines(log.path)
    if tamper == "edit":
        lines[2] = lines[2].replace(b'"i":2', b'"i":9')
    elif tamper == "remove_middle":
        del lines[2]
    elif tamper == "remove_last_keeps_valid_prefix":
        # Truncar o fim mantém uma cadeia válida; é detectado pelas checagens de
        # eventos obrigatórios da sessão (ver test_tampering).
        del lines[-1]
        _write(log.path, lines)
        assert verify_chain(log.path).ok
        return
    elif tamper == "reorder":
        lines[1], lines[2] = lines[2], lines[1]
    elif tamper == "insert":
        lines.insert(2, lines[2])
    _write(log.path, lines)
    assert not verify_chain(log.path).ok
