#!/usr/bin/env python
"""Verificador externo de sessões do Daldegan (SPEC §12).

Uso:
    python scripts/verify_session.py <SESSION_PATH> [--json]

Este script NÃO importa nada da aplicação. É uma segunda implementação,
independente, das regras do protocolo 1.0 (stdlib + scipy), para que qualquer
pessoa possa auditar uma sessão sem confiar no código da aplicação web.

Âncoras: um adversário com acesso ao disco pode reescrever a cadeia inteira do
audit.log. Para detectar isso, anote fora da máquina o "código de auditoria"
exibido pela interface (hash de uma entrada do log) e informe-o com --anchor.

Exit code: 0 = INTEGRIDADE: OK, 1 = INTEGRIDADE: FALHOU, 2 = erro de uso.
"""

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64
TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
HEADER = "event_id,sequence_number,bit,timestamp_utc"
FLOAT_DECIMALS = 12
TOL = 1e-9
SUPPORTED_PROTOCOLS = {"1.0"}
AUDIT_FIELDS = {"seq", "timestamp", "session_id", "event", "metadata",
                "hash_previous_log_entry", "hash_current_log_entry"}
FINGERPRINT_FIELDS = ("module", "test_mode", "planned_event_count", "planned_duration_seconds",
                      "target_selection_method", "statistical_test", "alternative_hypothesis",
                      "alpha", "protocol_version")
ORDER = {
    "MODULE_1": ["PREREGISTERED", "TARGET_SELECTED", "INTENTION_STARTED", "INTENTION_COMPLETED",
                 "GENERATION_STARTED", "DATA_SEALED"],
    "MODULE_2": ["PREREGISTERED", "GENERATION_STARTED", "DATA_SEALED", "TARGET_SELECTED",
                 "INTENTION_STARTED", "INTENTION_COMPLETED"],
}
ORDER["CONTROL"] = ORDER["MODULE_2"]
STATEMENTS = {
    False: "Não foi detectado desvio estatisticamente significativo.",
    True: "Foi detectado um desvio estatisticamente significativo.",
}


# ---------------------------------------------------------------- primitivas

def rnd(obj):
    if isinstance(obj, float):
        return round(obj, FLOAT_DECIMALS)
    if isinstance(obj, dict):
        return {k: rnd(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [rnd(v) for v in obj]
    return obj


def canonical(obj) -> bytes:
    return json.dumps(rnd(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return sha_bytes(p.read_bytes())


def ts(value: str) -> datetime:
    return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)


def load_json(p: Path):
    try:
        return json.loads(p.read_bytes().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def same(a, b) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= TOL
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def decode_block(block: dict) -> bytes:
    """Protocolo 1.0: uint8 → um byte por inteiro; hex16 → bytes.fromhex por item."""
    params = block["request_params"]
    payload = json.loads(block["body"])
    if payload.get("success") is not True:
        raise ValueError("resposta sem success=true")
    data = payload["data"]
    if len(data) != params["length"]:
        raise ValueError("tamanho de data diferente de length")
    if params["type"] == "uint8":
        if not all(type(v) is int and 0 <= v <= 255 for v in data):
            raise ValueError("uint8 inválido")
        return bytes(data)
    if params["type"] == "hex16":
        size = params.get("size", 1)
        if not all(isinstance(v, str) and len(v) == 4 * size for v in data):
            raise ValueError("hex16 inválido")
        return b"".join(bytes.fromhex(v) for v in data)
    raise ValueError(f"tipo não suportado: {params['type']}")


def bits_msb_first(data: bytes) -> list[int]:
    out = []
    for byte in data:
        for shift in range(7, -1, -1):
            out.append((byte >> shift) & 1)
    return out


def binomial(n: int, hits: int, alternative: str, alpha: float) -> dict:
    from scipy.stats import binomtest

    alt = {"TWO_SIDED": "two-sided", "GREATER": "greater"}[alternative]
    res = binomtest(hits, n, p=0.5, alternative=alt)
    ci = binomtest(hits, n, p=0.5).proportion_ci(0.95, method="exact")
    p = float(min(1.0, res.pvalue))
    observed = hits / n
    return {
        "observed_proportion": observed,
        "expected_proportion": 0.5,
        "absolute_deviation": observed - 0.5,
        "deviation_pp": 100 * (observed - 0.5),
        "z_score": (hits - n / 2) / math.sqrt(n / 4),
        "p_value": p,
        "ci_95": [float(ci.low), float(ci.high)],
        "significant": p < alpha,
        "result_statement": STATEMENTS[p < alpha],
    }


# ---------------------------------------------------------------- verificação

class Checks:
    def __init__(self):
        self.items = []

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        self.items.append({"name": name, "ok": bool(ok), "detail": "" if ok else detail})
        return ok

    @property
    def ok(self) -> bool:
        return bool(self.items) and all(i["ok"] for i in self.items)


def verify(session_dir: Path, anchors: list[str] | None = None) -> Checks:
    c = Checks()
    sid = session_dir.name
    files = {name: session_dir / name for name in
             ("preregistration.json", "manifest.json", "events.csv", "qrng_raw.jsonl", "audit.log")}

    # 1. arquivos
    missing = [n for n, p in files.items() if not p.exists()]
    if not c.add("1. arquivos presentes", not missing, f"ausentes: {missing}"):
        return c

    # 2. manifesto e pré-registro
    prereg = load_json(files["preregistration.json"])
    manifest = load_json(files["manifest.json"])
    if not c.add("2. manifest.json e preregistration.json legíveis",
                 isinstance(prereg, dict) and isinstance(manifest, dict), "JSON inválido"):
        return c
    c.add("2a. versão de protocolo suportada", prereg.get("protocol_version") in SUPPORTED_PROTOCOLS,
          f"protocolo {prereg.get('protocol_version')!r} não suportado por este verificador")
    c.add("2b. arquivos JSON em forma canônica",
          files["preregistration.json"].read_bytes() == canonical(prereg)
          and files["manifest.json"].read_bytes() == canonical(manifest),
          "JSON não está na serialização canônica")
    c.add("2c. session_id consistente",
          prereg.get("session_id") == sid == manifest.get("session_id"), "session_id divergente")
    try:
        fp = sha_bytes(canonical({k: prereg[k] for k in FINGERPRINT_FIELDS}))
    except KeyError:
        fp = None
    c.add("2d. fingerprint do protocolo", fp is not None and fp == prereg.get("protocol_fingerprint"),
          "fingerprint não confere")

    # 8-9. audit log e cadeia
    entries, chain_ok, chain_detail = [], True, ""
    try:
        raw_lines = files["audit.log"].read_text(encoding="utf-8").split("\n")
        if raw_lines and raw_lines[-1] == "":
            raw_lines = raw_lines[:-1]
        entries = [json.loads(line) for line in raw_lines]
    except Exception as exc:  # noqa: BLE001
        chain_ok, chain_detail = False, f"audit.log ilegível: {exc}"
    prev = GENESIS
    for i, e in enumerate(entries, start=1):
        if not chain_ok:
            break
        if not isinstance(e, dict) or set(e) != AUDIT_FIELDS:
            chain_ok, chain_detail = False, f"entrada {i}: campos inválidos"
        elif e["seq"] != i or e["session_id"] != sid:
            chain_ok, chain_detail = False, f"entrada {i}: seq/session_id inválido"
        elif e["hash_previous_log_entry"] != prev:
            chain_ok, chain_detail = False, f"entrada {i}: hash anterior não confere"
        else:
            body = {k: v for k, v in e.items() if k != "hash_current_log_entry"}
            if sha_bytes(canonical(body)) != e["hash_current_log_entry"]:
                chain_ok, chain_detail = False, f"entrada {i}: hash da entrada não confere"
            prev = e["hash_current_log_entry"]
    if not entries:
        chain_ok, chain_detail = False, chain_detail or "audit.log vazio"
    c.add("8-9. cadeia de hashes do audit.log", chain_ok, chain_detail)
    known = {e.get("hash_current_log_entry") for e in entries if isinstance(e, dict)}
    for anchor in anchors or []:
        c.add(f"8a. âncora externa {anchor[:12]}… presente no audit.log", anchor.lower() in known,
              "código anotado fora da máquina não existe nesta cadeia (log reescrito?)")

    by_event = {}
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict):
            by_event.setdefault(e.get("event"), []).append(e)

    def one(name):
        found = by_event.get(name, [])
        return found[0] if len(found) == 1 else None

    pre_e, seal_e = one("PREREGISTERED"), one("DATA_SEALED")
    if not c.add("9a. eventos PREREGISTERED e DATA_SEALED", pre_e is not None and seal_e is not None,
                 "ausentes ou duplicados"):
        return c

    # 3-4. hashes
    h_pre, h_man = sha_file(files["preregistration.json"]), sha_file(files["manifest.json"])
    h_ev, h_raw = sha_file(files["events.csv"]), sha_file(files["qrng_raw.jsonl"])
    sm = seal_e["metadata"]
    c.add("3-4. SHA-256 preregistration.json",
          {pre_e["metadata"].get("preregistration_sha256"), manifest.get("preregistration_sha256"),
           sm.get("preregistration_sha256")} == {h_pre}, "não confere")
    c.add("3-4. SHA-256 manifest.json", sm.get("manifest_sha256") == h_man, "não confere")
    c.add("3-4. SHA-256 events.csv", {manifest.get("events_sha256"), sm.get("events_sha256")} == {h_ev},
          "não confere")
    c.add("3-4. SHA-256 qrng_raw.jsonl", {manifest.get("qrng_raw_sha256"), sm.get("qrng_raw_sha256")} == {h_raw},
          "não confere")

    # 5-7. eventos
    bits, stamps, fmt_err = [], [], ""
    raw = files["events.csv"].read_bytes()
    try:
        text = raw.decode("utf-8")
        if "\r" in text or raw.startswith(b"\xef\xbb\xbf") or not text.endswith("\n"):
            raise ValueError("codificação/fim de linha fora do formato")
        lines = text[:-1].split("\n")
        if lines[0] != HEADER:
            raise ValueError("cabeçalho inválido")
        for k, line in enumerate(lines[1:], start=1):
            parts = line.split(",")
            if len(parts) != 4:
                raise ValueError(f"linha {k} malformada")
            if parts[1] != str(k):
                raise ValueError(f"sequência quebrada na linha {k}")
            if parts[0] != f"{sid}-{k:06d}":
                raise ValueError(f"event_id inválido na linha {k}")
            if parts[2] not in ("0", "1"):
                raise ValueError(f"valor não binário na linha {k}")
            bits.append(int(parts[2]))
            stamps.append(parts[3])
    except ValueError as exc:
        fmt_err = str(exc)
    c.add("6. eventos apenas 0/1", "binário" not in fmt_err, fmt_err)
    c.add("7. sequência e formato de events.csv", not fmt_err, fmt_err)
    n = prereg.get("planned_event_count")
    c.add("5. número de eventos",
          len(bits) == n == manifest.get("event_count") == manifest.get("number_of_bits_received"),
          "número de eventos não confere com manifesto/pré-registro")
    c.add("5a. coleta completa", manifest.get("partial") is False, "sessão parcial (QRNG_ERROR)")

    try:
        raw_bits, raw_ts = [], []
        for line in files["qrng_raw.jsonl"].read_text(encoding="utf-8").split("\n"):
            if not line:
                continue
            block = json.loads(line)
            new = bits_msb_first(decode_block(block))
            raw_bits.extend(new)
            raw_ts.extend([block["response_timestamp"]] * len(new))
        ok = raw_bits[: len(bits)] == bits and raw_ts[: len(bits)] == stamps and len(raw_bits) >= len(bits)
        c.add("7a. eventos derivados das respostas brutas", ok, "events.csv difere das respostas brutas")
    except Exception as exc:  # noqa: BLE001
        c.add("7a. eventos derivados das respostas brutas", False, f"qrng_raw.jsonl inválido: {exc}")

    source = (prereg.get("random_source") or {}).get("source_type")
    c.add("7b. fonte declarada = fonte usada",
          source == manifest.get("source_type")
          and (source == "PSEUDORANDOM_TEST") == bool(prereg.get("test_mode")) == sid.startswith("DALTEST-"),
          "fonte/modo divergentes")

    # alvo e cronologia
    module = prereg.get("module")
    targets = by_event.get("TARGET_SELECTED", [])
    target = targets[0]["metadata"].get("target") if len(targets) == 1 else None
    analysis_path = session_dir / "analysis.json"
    complete = analysis_path.exists() or "REVEAL_REQUESTED" in by_event
    order = ORDER.get(module)
    if order is None:
        c.add("9b. módulo conhecido", False, f"módulo {module!r}")
        return c
    if module == "MODULE_1":
        c.add("9b. alvo pré-registrado = alvo registrado",
              prereg.get("planned_target") in (0, 1) and target == prereg.get("planned_target"), "alvo divergente")
    else:
        c.add("9b. alvo não pré-registrado e escolhido após selamento",
              prereg.get("planned_target") is None and (target in (0, 1) or (not complete and not targets)),
              "alvo inválido")
    present = [name for name in order if name in by_event]
    t_ok = present == order if complete else present == order[: len(present)]
    seqs = [by_event[name][0]["seq"] for name in present if len(by_event[name]) == 1]
    t_ok = t_ok and len(seqs) == len(present) and seqs == sorted(seqs)
    st, done = one("INTENTION_STARTED"), one("INTENTION_COMPLETED")
    if t_ok and st and done:
        dur = prereg.get("planned_duration_seconds")
        t_ok = (ts(done["timestamp"]) - ts(st["timestamp"])).total_seconds() >= dur \
            and st["metadata"].get("duration_seconds") == dur
    c.add("9c. cronologia (ordem e duração da intenção)", t_ok, "ordem ou duração inválida")

    # 10-11. estatística
    if analysis_path.exists():
        analysis = load_json(analysis_path)
        done_e = one("ANALYSIS_COMPLETED")
        ok = isinstance(analysis, dict) and done_e is not None \
            and sha_file(analysis_path) == done_e["metadata"].get("analysis_sha256")
        c.add("11a. SHA-256 analysis.json", ok, "não confere com o audit.log")
        if isinstance(analysis, dict) and target in (0, 1) and bits:
            ones = sum(bits)
            hits = ones if target == 1 else len(bits) - ones
            expected = {
                "n": len(bits), "ones": ones, "zeros": len(bits) - ones, "hits": hits, "target": target,
                "proportion_of_ones": ones / len(bits), "participants_count": prereg.get("participants_count"),
                "alternative_hypothesis": prereg.get("alternative_hypothesis"), "alpha": prereg.get("alpha"),
                "preregistration_sha256": h_pre, "manifest_sha256": h_man, "events_sha256": h_ev,
                **binomial(len(bits), hits, prereg["alternative_hypothesis"], prereg["alpha"]),
            }
            diverging = [k for k, v in expected.items() if not same(rnd(v), analysis.get(k))]
            c.add("10-11. estatísticas recalculadas = analysis.json", not diverging,
                  f"divergentes: {', '.join(diverging)}")
    else:
        c.add("10-11. análise", True)  # ainda não revelada: nada a comparar

    return c


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verificador externo de sessões do Daldegan")
    parser.add_argument("session_path", type=Path)
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    parser.add_argument("--anchor", action="append", default=[], metavar="HASH",
                        help="código de auditoria anotado fora da máquina (pode repetir)")
    args = parser.parse_args(argv)
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")

    if not args.session_path.is_dir():
        print(f"erro: {args.session_path} não é um diretório de sessão", file=sys.stderr)
        return 2

    checks = verify(args.session_path, args.anchor)
    verdict = "INTEGRIDADE: OK" if checks.ok else "INTEGRIDADE: FALHOU"
    if args.json:
        print(json.dumps({"session": args.session_path.name, "ok": checks.ok, "verdict": verdict,
                          "checks": checks.items}, ensure_ascii=False, indent=2))
    else:
        print(f"Sessão: {args.session_path.name}")
        for item in checks.items:
            mark = "OK    " if item["ok"] else "FALHOU"
            print(f"  [{mark}] {item['name']}" + (f" — {item['detail']}" if item["detail"] else ""))
        print()
        print(verdict)
    return 0 if checks.ok else 1


if __name__ == "__main__":
    sys.exit(main())
