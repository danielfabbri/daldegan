"""Fábrica de fontes. Decide APENAS pelo source_type declarado no pré-registro.

Nunca faz fallback: se a fonte quântica não puder ser criada, levanta
SourceUnavailable.
"""

from collections.abc import Callable

from ..config import Settings
from ..errors import SourceUnavailable
from ..models.enums import SourceType
from .anu import QuantumRandomSource
from .base import RandomSource
from .local import LocalRandomSource

SourceFactory = Callable[[SourceType], RandomSource]


def default_factory(settings: Settings) -> SourceFactory:
    def make(source_type: SourceType) -> RandomSource:
        if source_type == SourceType.QUANTUM:
            if not settings.qrng_api_key:
                raise SourceUnavailable(
                    "Fonte quântica não configurada: defina DALDEGAN_QRNG_API_KEY "
                    "(chave gratuita em https://quantumnumbers.anu.edu.au)."
                )
            return QuantumRandomSource(
                api_key=settings.qrng_api_key,
                endpoint=settings.qrng_endpoint,
                data_type=settings.qrng_data_type,
                timeout_s=settings.qrng_timeout_s,
                min_interval_s=settings.qrng_min_interval_s,
            )
        if source_type == SourceType.PSEUDORANDOM_TEST:
            return LocalRandomSource()
        raise SourceUnavailable(f"tipo de fonte desconhecido: {source_type}")

    return make


def checked(factory: SourceFactory, source_type: SourceType) -> RandomSource:
    """Garante que a fonte devolvida é do tipo declarado (INV-02)."""
    source = factory(source_type)
    if source.source_type != source_type:
        raise SourceUnavailable(
            f"fábrica devolveu fonte {source.source_type} para sessão {source_type}; recusado"
        )
    return source
