from enum import StrEnum


class Module(StrEnum):
    MODULE_1 = "MODULE_1"  # intenção antes da geração
    MODULE_2 = "MODULE_2"  # intenção depois da geração (dados cegos)
    CONTROL = "CONTROL"  # mesmo fluxo do Módulo 2, período neutro


class State(StrEnum):
    CREATED = "CREATED"
    PRE_REGISTERED = "PRE_REGISTERED"
    GENERATING = "GENERATING"
    SEALED = "SEALED"
    TARGET_SELECTED = "TARGET_SELECTED"
    INTENTION_RUNNING = "INTENTION_RUNNING"
    REVEAL_PENDING = "REVEAL_PENDING"
    REVEALED = "REVEALED"
    ANALYZED = "ANALYZED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"
    QRNG_ERROR = "QRNG_ERROR"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({State.COMPLETED, State.INVALIDATED, State.QRNG_ERROR, State.CANCELLED})

# Estados em que os resultados já podem ser lidos.
REVEALED_STATES = frozenset({State.REVEALED, State.ANALYZED, State.COMPLETED})


class SourceType(StrEnum):
    QUANTUM = "QUANTUM"
    PSEUDORANDOM_TEST = "PSEUDORANDOM_TEST"


class TargetSelectionMethod(StrEnum):
    PARTICIPANT = "PARTICIPANT"
    SYSTEM_QUANTUM = "SYSTEM_QUANTUM"
    # Controle: alvo-placebo sorteado após o selamento e oculto até a revelação.
    SYSTEM_QUANTUM_SHAM = "SYSTEM_QUANTUM_SHAM"


class Alternative(StrEnum):
    TWO_SIDED = "TWO_SIDED"
    GREATER = "GREATER"


class StatisticalTest(StrEnum):
    BINOMIAL_EXACT = "BINOMIAL_EXACT"
