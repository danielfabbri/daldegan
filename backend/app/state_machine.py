"""Máquina de estados das sessões (SPEC §5).

As transições permitidas ficam numa tabela explícita por módulo; qualquer
outra lança IllegalTransition.
"""

from .errors import IllegalTransition
from .models.enums import TERMINAL_STATES, Module, State

S = State

_MODULE_1 = {
    S.CREATED: {S.PRE_REGISTERED, S.CANCELLED, S.QRNG_ERROR},  # QRNG_ERROR: falha ao sortear o alvo
    S.PRE_REGISTERED: {S.TARGET_SELECTED, S.CANCELLED},
    S.TARGET_SELECTED: {S.INTENTION_RUNNING, S.CANCELLED},
    S.INTENTION_RUNNING: {S.GENERATING},
    S.GENERATING: {S.SEALED, S.QRNG_ERROR},
    S.SEALED: {S.REVEAL_PENDING},
    S.REVEAL_PENDING: {S.REVEALED},
    S.REVEALED: {S.ANALYZED},
    S.ANALYZED: {S.COMPLETED},
}

_MODULE_2 = {
    S.CREATED: {S.PRE_REGISTERED, S.CANCELLED},
    S.PRE_REGISTERED: {S.GENERATING, S.CANCELLED},
    S.GENERATING: {S.SEALED, S.QRNG_ERROR},
    S.SEALED: {S.TARGET_SELECTED},
    S.TARGET_SELECTED: {S.INTENTION_RUNNING},
    S.INTENTION_RUNNING: {S.REVEAL_PENDING},
    S.REVEAL_PENDING: {S.REVEALED},
    S.REVEALED: {S.ANALYZED},
    S.ANALYZED: {S.COMPLETED},
}

TRANSITIONS: dict[Module, dict[State, set[State]]] = {
    Module.MODULE_1: _MODULE_1,
    Module.MODULE_2: _MODULE_2,
    Module.CONTROL: _MODULE_2,
}


def allowed_targets(module: Module, current: State) -> set[State]:
    if current in TERMINAL_STATES:
        return set()
    allowed = set(TRANSITIONS[module].get(current, set()))
    # Falha de integridade pode invalidar qualquer sessão não terminal.
    allowed.add(S.INVALIDATED)
    return allowed


def check_transition(module: Module, current: State, target: State) -> None:
    if target not in allowed_targets(module, current):
        raise IllegalTransition(f"transição ilegal para {module}: {current} → {target}")


def require_state(current: State, *expected: State) -> None:
    if current not in expected:
        names = ", ".join(expected)
        raise IllegalTransition(f"operação exige estado {names}; estado atual: {current}")
