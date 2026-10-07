"""DTOs de entrada da API."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .enums import Alternative, Module, TargetSelectionMethod

MIN_EVENTS = 10
MAX_EVENTS = 1_000_000
MIN_DURATION_S = 10
MAX_DURATION_S = 3600
MAX_PARTICIPANTS = 1000


class CreateSessionRequest(BaseModel):
    module: Module
    event_count: int = Field(ge=MIN_EVENTS, le=MAX_EVENTS)
    participants_count: int = Field(ge=1, le=MAX_PARTICIPANTS)
    participant_labels: list[str] | None = None
    duration_seconds: int = Field(ge=MIN_DURATION_S, le=MAX_DURATION_S)
    target_selection_method: TargetSelectionMethod = TargetSelectionMethod.PARTICIPANT
    target: Literal[0, 1] | None = None
    alternative_hypothesis: Alternative = Alternative.TWO_SIDED
    test_mode: bool = False

    @model_validator(mode="after")
    def _check(self):
        if self.participant_labels is not None:
            if len(self.participant_labels) != self.participants_count:
                raise ValueError("participant_labels deve ter participants_count itens")
            if any(len(label) > 60 for label in self.participant_labels):
                raise ValueError("rótulos de participante devem ter no máximo 60 caracteres")

        if self.module == Module.CONTROL:
            if self.target is not None:
                raise ValueError("a sessão Controle não tem alvo escolhido")
            self.target_selection_method = TargetSelectionMethod.SYSTEM_QUANTUM_SHAM
            return self

        if self.target_selection_method == TargetSelectionMethod.SYSTEM_QUANTUM_SHAM:
            raise ValueError("SYSTEM_QUANTUM_SHAM é exclusivo da sessão Controle")

        if self.module == Module.MODULE_1:
            if self.target_selection_method == TargetSelectionMethod.PARTICIPANT and self.target is None:
                raise ValueError("Módulo 1 exige o alvo antes da geração")
            if self.target_selection_method == TargetSelectionMethod.SYSTEM_QUANTUM and self.target is not None:
                raise ValueError("alvo sorteado pelo sistema não pode ser informado")
        else:  # MODULE_2: alvo só depois do selamento
            if self.target is not None:
                raise ValueError("no Módulo 2 o alvo é escolhido depois da geração")
        return self


class SelectTargetRequest(BaseModel):
    """Escolha do alvo no Módulo 2. O método já foi fixado no pré-registro:
    PARTICIPANT exige `target`; SYSTEM_QUANTUM exige `target` ausente."""

    target: Literal[0, 1] | None = None


class CumulativeRequest(BaseModel):
    mode: Literal["PROTOCOL", "MANUAL"]
    fingerprint: str | None = None
    session_ids: list[str] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.mode == "PROTOCOL" and not self.fingerprint:
            raise ValueError("modo PROTOCOL exige fingerprint")
        if self.mode == "MANUAL" and not self.session_ids:
            raise ValueError("modo MANUAL exige session_ids")
        return self
