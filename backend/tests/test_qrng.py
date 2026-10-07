"""Fontes de aleatoriedade: conversão de bits, adapter ANU (HTTP mockado), fábrica."""

import json

import httpx
import pytest

from backend.app.config import Settings
from backend.app.errors import SourceUnavailable
from backend.app.models.enums import SourceType
from backend.app.qrng.anu import QuantumRandomSource
from backend.app.qrng.base import QRNGError
from backend.app.qrng.bits import MalformedResponse, bits_from_raw_blocks, bytes_to_bits, decode_response
from backend.app.qrng.factory import checked, default_factory
from backend.app.qrng.local import LocalRandomSource


def test_bytes_to_bits_is_msb_first():
    assert bytes_to_bits(bytes([0b10110000])) == [1, 0, 1, 1, 0, 0, 0, 0]
    assert bytes_to_bits(bytes([0, 255])) == [0] * 8 + [1] * 8


def test_decode_uint8_and_hex16():
    assert decode_response('{"success":true,"data":[1,255],"type":"uint8","length":2}', "uint8", 2) == b"\x01\xff"
    body = json.dumps({"success": True, "data": ["a1b2c3d4"], "type": "hex16", "length": 1})
    assert decode_response(body, "hex16", 1, 2) == bytes.fromhex("a1b2c3d4")


@pytest.mark.parametrize(
    "body",
    [
        "not json",
        '{"success":false,"data":[1]}',
        '{"success":true,"data":[1]}',  # length errado
        '{"success":true,"data":[1,256]}',
        '{"success":true,"data":[1,true]}',
    ],
)
def test_decode_rejects_malformed(body):
    with pytest.raises(MalformedResponse):
        decode_response(body, "uint8", 2)


def _anu_transport(fail_at: int | None = None, status: int = 200, log=None):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if log is not None:
            log.append(request)
        i = calls["n"]
        calls["n"] += 1
        if fail_at is not None and i >= fail_at:
            return httpx.Response(status, text='{"message":"Internal error"}')
        length = int(request.url.params["length"])
        data = [(i * 7 + k) % 256 for k in range(length)]
        return httpx.Response(200, json={"type": "uint8", "length": length, "data": data, "success": True})

    return httpx.MockTransport(handler)


def _anu(transport, **kw):
    return QuantumRandomSource(api_key="secret-key", endpoint="https://api.example/qrng",
                               min_interval_s=0, transport=transport, **kw)


async def test_anu_request_format_and_multiple_blocks_in_order():
    requests = []
    source = _anu(_anu_transport(log=requests))
    received = []
    result = await source.get_bits(10_000, on_block=received.append)
    assert len(result.bits) == 10_000
    assert len(received) == 2  # 1250 bytes = 1024 + 226
    assert [r.url.params["length"] for r in requests] == ["1024", "226"]
    assert all(r.url.params["type"] == "uint8" for r in requests)
    assert all(r.headers["x-api-key"] == "secret-key" for r in requests)
    assert bits_from_raw_blocks(received, 10_000) == result.bits


def test_anu_plan_hex16():
    source = _anu(_anu_transport(), data_type="hex16")
    plans = source.plan_requests(163_840 + 1)
    assert plans[0] == {"length": 1024, "type": "hex16", "size": 10}
    assert len(plans) == 2


async def test_anu_failure_mid_session_preserves_received_blocks():
    source = _anu(_anu_transport(fail_at=1, status=500))
    received = []
    with pytest.raises(QRNGError) as info:
        await source.get_bits(10_000, on_block=received.append)
    assert len(info.value.raw_blocks) == 1
    assert len(received) == 1
    assert info.value.failed_response["http_status"] == 500


async def test_anu_malformed_response_is_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={"success": False}))
    with pytest.raises(QRNGError):
        await _anu(transport).get_bits(8)


async def test_anu_transport_error_retries_then_fails():
    attempts = []

    def handler(request):
        attempts.append(request)
        raise httpx.ConnectError("offline")

    retries = []
    with pytest.raises(QRNGError):
        await _anu(httpx.MockTransport(handler)).get_bits(8, on_retry=lambda a, r: retries.append(a))
    assert len(attempts) == 3
    assert retries == [1, 2]


def test_anu_requires_api_key():
    with pytest.raises(ValueError):
        QuantumRandomSource(api_key="", endpoint="https://x")


def test_factory_without_key_never_falls_back_to_pseudorandom(tmp_path):
    make = default_factory(Settings(data_dir=tmp_path, qrng_api_key=None, _env_file=None))
    with pytest.raises(SourceUnavailable):
        make(SourceType.QUANTUM)
    assert make(SourceType.PSEUDORANDOM_TEST).source_type == SourceType.PSEUDORANDOM_TEST


def test_factory_with_key_returns_quantum(tmp_path):
    make = default_factory(Settings(data_dir=tmp_path, qrng_api_key="k", _env_file=None))
    assert make(SourceType.QUANTUM).source_type == SourceType.QUANTUM


def test_checked_rejects_mismatched_source():
    with pytest.raises(SourceUnavailable):
        checked(lambda st: LocalRandomSource(seed=1), SourceType.QUANTUM)


async def test_local_source_is_reproducible_with_seed():
    a = await LocalRandomSource(seed=7).get_bits(100)
    b = await LocalRandomSource(seed=7).get_bits(100)
    assert a.bits == b.bits
    assert set(a.bits) <= {0, 1}


@pytest.mark.qrng_live
async def test_live_anu_api():
    settings = Settings()
    if not settings.qrng_api_key:
        pytest.skip("DALDEGAN_QRNG_API_KEY não configurada")
    source = default_factory(settings)(SourceType.QUANTUM)
    result = await source.get_bits(64)
    assert len(result.bits) == 64 and set(result.bits) <= {0, 1}
