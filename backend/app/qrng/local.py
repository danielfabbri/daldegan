"""LocalRandomSource — SOMENTE para testes automatizados e modo teste explícito.

Gera respostas no mesmo formato da ANU (uint8), para que a persistência e a
verificação sejam idênticas. Toda sessão que usa esta fonte é marcada
PSEUDORANDOM_TEST e nunca entra em análises experimentais.
"""

import json
import random
import secrets
from datetime import datetime, timezone

from ..audit.hashing import format_ts
from ..models.enums import SourceType
from .base import BitsResult, BlockCallback, QRNGError, RandomSource, RetryCallback, maybe_await
from .bits import bits_needed_to_bytes, bytes_to_bits

MAX_LENGTH = 1024


class LocalRandomSource(RandomSource):
    source_type = SourceType.PSEUDORANDOM_TEST
    source_endpoint = None
    data_type = "uint8"

    def __init__(self, seed: int | None = None, fail_after_blocks: int | None = None, byte_values: bytes | None = None):
        """
        seed: torna a sequência reprodutível (testes). None usa secrets.
        fail_after_blocks: simula falha da fonte depois de N blocos (testes).
        byte_values: bytes fixos a devolver em ordem (testes estatísticos).
        """
        self.seed = seed
        self._rng = random.Random(seed) if seed is not None else None
        self._fail_after = fail_after_blocks
        self._fixed = bytearray(byte_values) if byte_values is not None else None
        self.source_name = "LocalRandomSource (pseudoaleatória, " + ("seed=%d" % seed if seed is not None else "secrets") + ")"

    def describe(self) -> dict:
        d = super().describe()
        d["seed"] = self.seed
        return d

    def _bytes(self, n: int) -> bytes:
        if self._fixed is not None:
            if len(self._fixed) < n:
                raise QRNGError("bytes fixos insuficientes")
            out = bytes(self._fixed[:n])
            del self._fixed[:n]
            return out
        if self._rng is not None:
            return self._rng.randbytes(n)
        return secrets.token_bytes(n)

    async def get_bits(
        self,
        count: int,
        on_block: BlockCallback | None = None,
        on_retry: RetryCallback | None = None,
    ) -> BitsResult:
        remaining = bits_needed_to_bytes(count)
        blocks: list[dict] = []
        bits: list[int] = []
        bit_ts: list[str] = []
        index = 0
        while remaining > 0:
            if self._fail_after is not None and index >= self._fail_after:
                raise QRNGError("falha simulada da fonte", blocks)
            n = min(MAX_LENGTH, remaining)
            ts = format_ts(datetime.now(timezone.utc))
            data = self._bytes(n)
            params = {"length": n, "type": "uint8"}
            body = json.dumps({"type": "uint8", "length": n, "data": list(data), "success": True})
            block = {
                "index": index,
                "request_timestamp": ts,
                "response_timestamp": ts,
                "request_params": params,
                "http_status": 200,
                "body": body,
            }
            blocks.append(block)
            if on_block:
                await maybe_await(on_block(block))
            new_bits = bytes_to_bits(data)
            bits.extend(new_bits)
            bit_ts.extend([ts] * len(new_bits))
            remaining -= n
            index += 1
        return BitsResult(
            bits=bits[:count],
            raw_blocks=blocks,
            bits_requested=count,
            bits_received=min(len(bits), count),
            raw_bytes_received=sum(b["request_params"]["length"] for b in blocks),
            first_request_timestamp=blocks[0]["request_timestamp"],
            last_response_timestamp=blocks[-1]["response_timestamp"],
            bit_timestamps=bit_ts[:count],
        )
