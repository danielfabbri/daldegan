"""QuantumRandomSource — ANU Quantum Numbers (AQN).

Implementado conforme docs/qrng-anu.md (documentação oficial acessada em
2026-10-07):
- GET https://api.quantumnumbers.anu.edu.au?length=..&type=..[&size=..]
- header x-api-key
- length 1–1024; type uint8|uint16|hex8|hex16; size 1–10 (só hex)
- plano gratuito: 100 requisições/mês, 1 requisição/s
"""

import asyncio
from datetime import datetime, timezone

import httpx

from ..audit.hashing import format_ts
from ..models.enums import SourceType
from .base import BitsResult, BlockCallback, QRNGError, RandomSource, RetryCallback, maybe_await
from .bits import MalformedResponse, bits_needed_to_bytes, bytes_to_bits, decode_response

MAX_LENGTH = 1024
HEX16_BLOCK_SIZE = 10
MAX_RETRIES = 2


class QuantumRandomSource(RandomSource):
    source_type = SourceType.QUANTUM
    source_name = "ANU Quantum Numbers (AQN)"

    def __init__(
        self,
        api_key: str,
        endpoint: str,
        data_type: str = "uint8",
        timeout_s: float = 30.0,
        min_interval_s: float = 1.1,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise ValueError("API key ausente")
        if data_type not in ("uint8", "hex16"):
            raise ValueError("data_type deve ser uint8 ou hex16")
        self._api_key = api_key
        self.source_endpoint = endpoint
        self.data_type = data_type
        self._timeout = timeout_s
        self._min_interval = min_interval_s
        self._transport = transport

    @property
    def bytes_per_item(self) -> int:
        return 1 if self.data_type == "uint8" else 2 * HEX16_BLOCK_SIZE

    def plan_requests(self, bit_count: int) -> list[dict]:
        """Parâmetros de cada requisição necessária para obter bit_count bits."""
        remaining_bytes = bits_needed_to_bytes(bit_count)
        plans = []
        while remaining_bytes > 0:
            items = min(MAX_LENGTH, -(-remaining_bytes // self.bytes_per_item))
            params = {"length": items, "type": self.data_type}
            if self.data_type == "hex16":
                params["size"] = HEX16_BLOCK_SIZE
            plans.append(params)
            remaining_bytes -= items * self.bytes_per_item
        return plans

    def requests_needed(self, bit_count: int) -> int:
        return len(self.plan_requests(bit_count))

    async def get_bits(
        self,
        count: int,
        on_block: BlockCallback | None = None,
        on_retry: RetryCallback | None = None,
    ) -> BitsResult:
        if count < 1:
            raise ValueError("count deve ser >= 1")
        blocks: list[dict] = []
        bits: list[int] = []
        bit_ts: list[str] = []
        raw_bytes = 0
        headers = {"x-api-key": self._api_key}

        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            for index, params in enumerate(self.plan_requests(count)):
                if index > 0 and self._min_interval > 0:
                    await asyncio.sleep(self._min_interval)

                response = None
                request_ts = None
                for attempt in range(MAX_RETRIES + 1):
                    request_ts = format_ts(datetime.now(timezone.utc))
                    try:
                        response = await client.get(self.source_endpoint, params=params, headers=headers)
                        break
                    except httpx.TransportError as exc:
                        # Nenhum corpo foi recebido; retry é seguro e registrado.
                        if attempt == MAX_RETRIES:
                            raise QRNGError(f"falha de conexão com a fonte quântica: {exc}", blocks) from exc
                        if on_retry:
                            await maybe_await(on_retry(attempt + 1, f"{type(exc).__name__}: {exc}"))
                        await asyncio.sleep(self._min_interval)

                response_ts = format_ts(datetime.now(timezone.utc))
                body = response.text
                failed = {
                    "index": index,
                    "request_params": params,
                    "http_status": response.status_code,
                    "body": body[:2000],
                    "request_timestamp": request_ts,
                    "response_timestamp": response_ts,
                }
                if response.status_code != 200:
                    raise QRNGError(f"fonte quântica respondeu HTTP {response.status_code}", blocks, failed)
                try:
                    data = decode_response(body, params["type"], params["length"], params.get("size"))
                except MalformedResponse as exc:
                    raise QRNGError(f"resposta inválida da fonte quântica: {exc}", blocks, failed) from exc

                block = {
                    "index": index,
                    "request_timestamp": request_ts,
                    "response_timestamp": response_ts,
                    "request_params": params,
                    "http_status": response.status_code,
                    "body": body,
                }
                blocks.append(block)
                if on_block:
                    await maybe_await(on_block(block))
                new_bits = bytes_to_bits(data)
                bits.extend(new_bits)
                bit_ts.extend([response_ts] * len(new_bits))
                raw_bytes += len(data)

        return BitsResult(
            bits=bits[:count],
            raw_blocks=blocks,
            bits_requested=count,
            bits_received=min(len(bits), count),
            raw_bytes_received=raw_bytes,
            first_request_timestamp=blocks[0]["request_timestamp"] if blocks else None,
            last_response_timestamp=blocks[-1]["response_timestamp"] if blocks else None,
            bit_timestamps=bit_ts[:count],
        )
