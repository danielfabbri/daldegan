"""Conversão documentada de respostas da fonte em bits (SPEC §3.3, protocolo 1.0).

- uint8: cada inteiro 0–255 é um byte.
- hex16 (size N): cada item é uma string hexadecimal; bytes.fromhex(item),
  lida da esquerda para a direita.
- Cada byte gera 8 bits, MSB primeiro.
- Bytes consumidos na ordem exata de recebimento, bloco a bloco.
- Usam-se os primeiros N bits; nenhum outro pós-processamento é aplicado.
"""

import json

BIT_EXTRACTION_DESCRIPTION = (
    "Cada resposta é decodificada em bytes na ordem recebida (uint8: um byte por inteiro; "
    "hex16: bytes.fromhex de cada item, esquerda→direita). Cada byte gera 8 bits, MSB primeiro. "
    "Usam-se os primeiros N bits. Sem debiasing, XOR, embaralhamento ou qualquer outro pós-processamento."
)


class MalformedResponse(ValueError):
    pass


def bytes_to_bits(data: bytes) -> list[int]:
    return [(b >> shift) & 1 for b in data for shift in range(7, -1, -1)]


def bits_needed_to_bytes(bit_count: int) -> int:
    return (bit_count + 7) // 8


def decode_response(body: str, data_type: str, expected_length: int, block_size: int | None = None) -> bytes:
    """Valida e converte o corpo JSON de uma resposta em bytes."""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise MalformedResponse(f"resposta não é JSON: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise MalformedResponse("resposta sem success=true")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) != expected_length:
        raise MalformedResponse(f"esperados {expected_length} itens em data")

    if data_type == "uint8":
        if not all(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255 for v in data):
            raise MalformedResponse("valor uint8 fora do intervalo 0–255")
        return bytes(data)

    if data_type == "hex16":
        expected_chars = 4 * (block_size or 1)
        out = bytearray()
        for item in data:
            if not isinstance(item, str) or len(item) != expected_chars:
                raise MalformedResponse(f"item hex16 deve ter {expected_chars} caracteres")
            try:
                out += bytes.fromhex(item)
            except ValueError as exc:
                raise MalformedResponse("item hex16 inválido") from exc
        return bytes(out)

    raise MalformedResponse(f"tipo não suportado: {data_type}")


def bits_from_raw_blocks(blocks: list[dict], count: int | None = None) -> list[int]:
    """Re-deriva bits a partir dos blocos brutos preservados em qrng_raw.jsonl."""
    out: list[int] = []
    for block in blocks:
        params = block["request_params"]
        data = decode_response(block["body"], params["type"], params["length"], params.get("size"))
        out.extend(bytes_to_bits(data))
    return out if count is None else out[:count]
