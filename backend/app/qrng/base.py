"""Abstração de fonte de aleatoriedade (SPEC §3.1).

O restante do sistema só conhece RandomSource. Detalhes de API ficam nas
implementações.
"""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..models.enums import SourceType

# Recebe cada bloco bruto assim que chega, para persistência imediata.
BlockCallback = Callable[[dict], Awaitable[None] | None]
# Recebe (tentativa, motivo) a cada retry.
RetryCallback = Callable[[int, str], Awaitable[None] | None]


@dataclass
class BitsResult:
    bits: list[int]
    raw_blocks: list[dict]
    bits_requested: int
    bits_received: int
    raw_bytes_received: int
    first_request_timestamp: str | None
    last_response_timestamp: str | None
    # timestamp de resposta do bloco de onde veio cada bit
    bit_timestamps: list[str] = field(default_factory=list)


class QRNGError(Exception):
    """Falha da fonte. Carrega os blocos já recebidos para preservação."""

    def __init__(self, message: str, raw_blocks: list[dict] | None = None, failed_response: dict | None = None):
        super().__init__(message)
        self.raw_blocks = raw_blocks or []
        self.failed_response = failed_response


class RandomSource(ABC):
    source_type: SourceType
    source_name: str
    source_endpoint: str | None
    data_type: str

    def describe(self) -> dict:
        return {
            "source_type": str(self.source_type),
            "source_name": self.source_name,
            "source_endpoint": self.source_endpoint,
            "data_type": self.data_type,
        }

    @abstractmethod
    async def get_bits(
        self,
        count: int,
        on_block: BlockCallback | None = None,
        on_retry: RetryCallback | None = None,
    ) -> BitsResult: ...


async def maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value
