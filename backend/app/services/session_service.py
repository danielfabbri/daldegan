"""Orquestração dos fluxos experimentais (SPEC §6, §8).

Toda mudança de estado passa por _transition, que valida a transição na
máquina de estados, grava no audit.log e só depois atualiza o índice SQLite.
"""

import asyncio
from datetime import timedelta
from pathlib import Path

from ..audit.audit_log import AuditLog, verify_chain
from ..audit.hashing import format_ts, parse_ts, round_floats, sha256_bytes, sha256_file
from ..clock import Clock
from ..config import Settings
from ..environment import collect_environment
from ..errors import IllegalTransition, NotFound, SourceUnavailable, TooEarly
from ..models.api import CreateSessionRequest, SelectTargetRequest
from ..models.enums import Module, SourceType, State, TargetSelectionMethod
from ..qrng.base import QRNGError, RandomSource
from ..qrng.bits import BIT_EXTRACTION_DESCRIPTION, MalformedResponse
from ..qrng.factory import SourceFactory, checked
from ..state_machine import check_transition, require_state
from ..statistics.binomial import DEFAULT_ALPHA
from ..storage.index_db import IndexDB
from ..storage.session_store import SessionPaths, SessionStore
from ..version import PROTOCOL_VERSION, SOFTWARE_VERSION
from . import report_service
from .analysis_builder import build_analysis, build_events_csv, parse_events_csv
from .integrity import IntegrityReport, bits_and_timestamps_from_raw, read_raw_blocks, timeline_from_audit, verify_session
from .protocol import protocol_fingerprint


class SessionService:
    def __init__(self, settings: Settings, clock: Clock, source_factory: SourceFactory):
        self.settings = settings
        self.clock = clock
        self.source_factory = source_factory
        self.store = SessionStore(settings.sessions_dir, settings.test_sessions_dir)
        self.index = IndexDB(settings.index_db_path)
        self.global_log = AuditLog(settings.global_audit_path)
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------ util

    def _now(self):
        return self.clock.now()

    def _lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    def get_record(self, session_id: str) -> dict:
        paths = self.store.paths(session_id)  # valida o formato do id
        record = self.index.get(session_id)
        if record is None or not paths.root.exists():
            raise NotFound(f"sessão {session_id} não encontrada")
        return record

    def paths(self, session_id: str) -> SessionPaths:
        return self.store.paths(session_id)

    def _audit(self, session_id: str) -> AuditLog:
        return AuditLog(self.paths(session_id).audit)

    def _log(self, record: dict, event: str, metadata: dict | None = None) -> dict:
        return self._audit(record["session_id"]).append(record["session_id"], event, self._now(), metadata)

    def _transition(self, record: dict, to_state: State, event: str, metadata: dict | None = None, **fields) -> None:
        check_transition(Module(record["module"]), State(record["state"]), to_state)
        meta = dict(metadata or {})
        meta["state"] = str(to_state)
        self._log(record, event, meta)
        fields["state"] = str(to_state)
        fields["updated_at"] = format_ts(self._now())
        self.index.update(record["session_id"], **fields)
        record.update(fields)

    @staticmethod
    def _source_type(record: dict) -> SourceType:
        return SourceType.PSEUDORANDOM_TEST if record["test_mode"] else SourceType.QUANTUM

    def make_source(self, source_type: SourceType) -> RandomSource:
        return checked(self.source_factory, source_type)

    def requests_needed(self, event_count: int, test_mode: bool) -> int | None:
        """Quantas requisições à fonte uma sessão consumirá (informativo)."""
        try:
            source = self.make_source(SourceType.PSEUDORANDOM_TEST if test_mode else SourceType.QUANTUM)
        except SourceUnavailable:
            return None
        plan = getattr(source, "requests_needed", None)
        return plan(event_count) if plan else None

    async def _draw_target(self, record: dict, source: RandomSource, method: TargetSelectionMethod) -> int:
        """Sorteia o alvo com 1 bit de uma requisição separada (fora de events.csv)."""
        try:
            result = await source.get_bits(1)
        except QRNGError as exc:
            self._log(record, "QRNG_ERROR", {"stage": "TARGET_RANDOMIZATION", "message": str(exc),
                                              "failed_response": exc.failed_response})
            raise
        target = result.bits[0]
        self._log(
            record,
            "TARGET_RANDOMIZED",
            {
                "method": str(method),
                "target": target,
                "rule": "primeiro bit (MSB) do primeiro byte recebido",
                "source": source.describe(),
                "raw_block": result.raw_blocks[0],
            },
        )
        return target

    # --------------------------------------------------------------- criação

    async def create_session(self, req: CreateSessionRequest) -> dict:
        source_type = SourceType.PSEUDORANDOM_TEST if req.test_mode else SourceType.QUANTUM
        source = self.make_source(source_type)  # falha antes de criar qualquer coisa
        now = self._now()
        session_id, session_uuid, paths = self.store.create_session_dir(req.test_mode, now)
        created_at = format_ts(now)

        self.global_log.append(session_id, "SESSION_REGISTERED", now, {
            "module": str(req.module), "test_mode": req.test_mode, "dir": paths.root.name,
        })
        record = {
            "session_id": session_id,
            "session_uuid": session_uuid,
            "module": str(req.module),
            "test_mode": int(req.test_mode),
            "state": str(State.CREATED),
            "created_at": created_at,
            "planned_event_count": req.event_count,
            "planned_duration_seconds": req.duration_seconds,
            "participants_count": req.participants_count,
            "target": None,
            "target_selection_method": str(req.target_selection_method),
            "alternative_hypothesis": str(req.alternative_hypothesis),
            "alpha": DEFAULT_ALPHA,
            "bits_requested": req.event_count,
            "bits_received": 0,
            "integrity_status": "PENDING",
            "dir_path": str(paths.root),
            "updated_at": created_at,
        }
        self.index.insert(record)
        self._log(record, "SESSION_CREATED", {
            "state": str(State.CREATED), "module": str(req.module), "test_mode": req.test_mode,
            "source": source.describe(),
        })

        planned_target = req.target
        if req.module == Module.MODULE_1 and req.target_selection_method == TargetSelectionMethod.SYSTEM_QUANTUM:
            try:
                planned_target = await self._draw_target(record, source, req.target_selection_method)
            except QRNGError as exc:
                self._transition(record, State.QRNG_ERROR, "SESSION_ABORTED", {"reason": str(exc)})
                raise SourceUnavailable(f"não foi possível sortear o alvo: {exc}") from exc

        participant_labels = req.participant_labels or [f"Participante {i}" for i in range(1, req.participants_count + 1)]
        prereg = {
            "protocol_version": PROTOCOL_VERSION,
            "software_version": SOFTWARE_VERSION,
            "session_id": session_id,
            "session_uuid": session_uuid,
            "module": str(req.module),
            "test_mode": req.test_mode,
            "random_source": source.describe(),
            "planned_event_count": req.event_count,
            "planned_duration_seconds": req.duration_seconds,
            "participants_count": req.participants_count,
            "participant_labels": participant_labels,
            "target_selection_method": str(req.target_selection_method),
            "planned_target": planned_target if req.module == Module.MODULE_1 else None,
            "statistical_test": "BINOMIAL_EXACT",
            "outcome_measure": "HITS",
            "null_hypothesis": "P(hit) = 0.5",
            "alternative_hypothesis": str(req.alternative_hypothesis),
            "alpha": DEFAULT_ALPHA,
            "confidence_level": 0.95,
            "creation_timestamp": created_at,
            "environment": collect_environment(),
        }
        prereg["protocol_fingerprint"] = protocol_fingerprint(prereg)
        data = self.store.write_json_once(paths.preregistration, prereg)
        prereg_sha = sha256_bytes(data)
        self.store.make_read_only(paths)

        self._transition(
            record, State.PRE_REGISTERED, "PREREGISTERED",
            {"preregistration_sha256": prereg_sha, "protocol_fingerprint": prereg["protocol_fingerprint"]},
            preregistration_sha256=prereg_sha,
            protocol_fingerprint=prereg["protocol_fingerprint"],
        )
        if req.module == Module.MODULE_1:
            self._transition(
                record, State.TARGET_SELECTED, "TARGET_SELECTED",
                {"target": planned_target, "method": str(req.target_selection_method)},
                target=planned_target, target_selected_at=format_ts(self._now()),
            )
        return record

    def preregistration(self, session_id: str) -> tuple[bytes, str]:
        self.get_record(session_id)
        data = self.paths(session_id).preregistration.read_bytes()
        return data, sha256_bytes(data)

    def cancel(self, session_id: str) -> dict:
        record = self.get_record(session_id)
        self._transition(record, State.CANCELLED, "SESSION_CANCELLED")
        return record

    # --------------------------------------------------------------- geração

    def begin_generation(self, session_id: str) -> dict:
        """Valida e entra em GENERATING. A coleta roda em run_generation."""
        record = self.get_record(session_id)
        module = Module(record["module"])
        if module == Module.MODULE_1:
            require_state(State(record["state"]), State.INTENTION_RUNNING)
            if not record.get("intention_completed_at"):
                raise IllegalTransition("Módulo 1: a geração só começa depois de concluída a intenção")
        else:
            require_state(State(record["state"]), State.PRE_REGISTERED)
        source = self.make_source(self._source_type(record))
        self.store.ensure_raw_file(self.paths(session_id))
        self._transition(
            record, State.GENERATING, "GENERATION_STARTED",
            {"bits_requested": record["planned_event_count"], "source": source.describe()},
            bits_received=0,
        )
        return record

    async def run_generation(self, session_id: str) -> dict:
        async with self._lock(session_id):
            record = self.get_record(session_id)
            require_state(State(record["state"]), State.GENERATING)
            paths = self.paths(session_id)
            n = record["planned_event_count"]
            received_bits = 0

            def on_block(block: dict) -> None:
                nonlocal received_bits
                self.store.append_raw_block(paths, block)
                received_bits += 8 * block["request_params"]["length"] * (
                    1 if block["request_params"]["type"] == "uint8" else 2 * block["request_params"].get("size", 1)
                )
                self._log(record, "QRNG_BLOCK_RECEIVED", {
                    "index": block["index"], "http_status": block["http_status"],
                    "request_params": block["request_params"],
                    "response_timestamp": block["response_timestamp"],
                })
                self.index.update(session_id, bits_received=min(received_bits, n))

            def on_retry(attempt: int, reason: str) -> None:
                self._log(record, "QRNG_RETRY", {"attempt": attempt, "reason": reason})

            try:
                source = self.make_source(self._source_type(record))
                result = await source.get_bits(n, on_block=on_block, on_retry=on_retry)
            except (QRNGError, SourceUnavailable) as exc:
                self._fail_generation(record, str(exc), getattr(exc, "failed_response", None))
                return record
            except Exception as exc:  # noqa: BLE001 — qualquer falha precisa ser registrada
                self._fail_generation(record, f"{type(exc).__name__}: {exc}", None)
                return record

            self._seal(record, paths, source, result.first_request_timestamp, result.last_response_timestamp)
        await self._after_seal(record)
        return record

    async def generate(self, session_id: str) -> dict:
        self.begin_generation(session_id)
        return await self.run_generation(session_id)

    def _write_events_and_manifest(self, record: dict, paths: SessionPaths, source_desc: dict,
                                   first_ts: str | None, last_ts: str | None, partial: bool) -> dict:
        """Deriva os eventos SEMPRE do qrng_raw.jsonl persistido."""
        n = record["planned_event_count"]
        blocks, _ = read_raw_blocks(paths.qrng_raw)
        valid_blocks = []
        for b in blocks:
            try:
                bits_and_timestamps_from_raw([b])
                valid_blocks.append(b)
            except (MalformedResponse, KeyError, TypeError):
                break
        bits, ts = bits_and_timestamps_from_raw(valid_blocks)
        bits, ts = bits[:n], ts[:n]
        events = build_events_csv(record["session_id"], bits, ts)
        self.store.write_bytes_once(paths.events, events)
        manifest = {
            "session_id": record["session_id"],
            "preregistration_sha256": record["preregistration_sha256"],
            "source_type": source_desc["source_type"],
            "source_name": source_desc["source_name"],
            "source_endpoint": source_desc["source_endpoint"],
            "source_data_type": source_desc.get("data_type"),
            "request_timestamp": first_ts or (valid_blocks[0]["request_timestamp"] if valid_blocks else None),
            "response_timestamp": last_ts or (valid_blocks[-1]["response_timestamp"] if valid_blocks else None),
            "number_of_bits_requested": n,
            "number_of_bits_received": len(bits),
            "number_of_raw_bytes_received": sum(
                len(bits_and_timestamps_from_raw([b])[0]) // 8 for b in valid_blocks
            ),
            "qrng_requests": len(blocks),
            "bit_extraction": BIT_EXTRACTION_DESCRIPTION,
            "partial": partial,
            "events_sha256": sha256_bytes(events),
            "qrng_raw_sha256": sha256_file(paths.qrng_raw),
            "event_count": len(bits),
            "sealed_timestamp": format_ts(self._now()),
        }
        data = self.store.write_json_once(paths.manifest, manifest)
        self.store.make_read_only(paths)
        return {
            "events_sha256": manifest["events_sha256"],
            "manifest_sha256": sha256_bytes(data),
            "qrng_raw_sha256": manifest["qrng_raw_sha256"],
            "preregistration_sha256": record["preregistration_sha256"],
            "event_count": len(bits),
        }

    def _seal(self, record: dict, paths: SessionPaths, source: RandomSource, first_ts, last_ts) -> None:
        self._log(record, "GENERATION_COMPLETED", {"bits_received": record["planned_event_count"]})
        hashes = self._write_events_and_manifest(record, paths, source.describe(), first_ts, last_ts, partial=False)
        self._transition(
            record, State.SEALED, "DATA_SEALED", hashes,
            events_sha256=hashes["events_sha256"], manifest_sha256=hashes["manifest_sha256"],
            bits_received=hashes["event_count"],
        )

    def _fail_generation(self, record: dict, message: str, failed_response: dict | None) -> None:
        """Preserva exatamente o que foi recebido e encerra a sessão em QRNG_ERROR."""
        paths = self.paths(record["session_id"])
        try:
            source_desc = self.make_source(self._source_type(record)).describe()
        except SourceUnavailable:
            source_desc = {"source_type": str(self._source_type(record)), "source_name": None,
                           "source_endpoint": None, "data_type": None}
        hashes = {}
        if not paths.events.exists() and paths.qrng_raw.exists():
            hashes = self._write_events_and_manifest(record, paths, source_desc, None, None, partial=True)
        self._transition(
            record, State.QRNG_ERROR, "QRNG_ERROR",
            {"message": message, "failed_response": failed_response, "partial": True, **hashes},
            invalid_reason=message, integrity_status="QRNG_ERROR",
            events_sha256=hashes.get("events_sha256"), manifest_sha256=hashes.get("manifest_sha256"),
        )

    async def _after_seal(self, record: dict) -> None:
        module = Module(record["module"])
        if module == Module.MODULE_1:
            self._transition(record, State.REVEAL_PENDING, "AWAITING_REVEAL")
        elif module == Module.CONTROL:
            try:
                await self._select_sham_target(record)
            except SourceUnavailable:
                pass  # fica em SEALED; a UI pode tentar o sorteio de novo

    def recover_interrupted(self) -> list[str]:
        """No startup: sessões presas em GENERATING vão para QRNG_ERROR (SPEC §3.5)."""
        recovered = []
        for record in self.index.by_state(str(State.GENERATING)):
            self._fail_generation(record, "geração interrompida (servidor reiniciado)", None)
            recovered.append(record["session_id"])
        return recovered

    # ---------------------------------------------------------- alvo/intenção

    async def _select_sham_target(self, record: dict) -> None:
        source = self.make_source(self._source_type(record))
        try:
            target = await self._draw_target(record, source, TargetSelectionMethod.SYSTEM_QUANTUM_SHAM)
        except QRNGError as exc:
            raise SourceUnavailable(f"não foi possível sortear o alvo-placebo: {exc}") from exc
        self._transition(
            record, State.TARGET_SELECTED, "TARGET_SELECTED",
            {"target": target, "method": str(TargetSelectionMethod.SYSTEM_QUANTUM_SHAM), "hidden_until_reveal": True},
            target=target, target_selected_at=format_ts(self._now()),
        )

    async def select_target(self, session_id: str, req: SelectTargetRequest) -> dict:
        async with self._lock(session_id):
            record = self.get_record(session_id)
            module = Module(record["module"])
            if module == Module.MODULE_1:
                raise IllegalTransition("no Módulo 1 o alvo é definido no pré-registro")
            require_state(State(record["state"]), State.SEALED)
            if module == Module.CONTROL:
                await self._select_sham_target(record)
                return record

            method = TargetSelectionMethod(record["target_selection_method"])
            if method == TargetSelectionMethod.PARTICIPANT:
                if req.target is None:
                    raise IllegalTransition("informe o alvo (0 ou 1)")
                target = req.target
            else:
                if req.target is not None:
                    raise IllegalTransition("o protocolo pré-registrou alvo sorteado pelo sistema")
                source = self.make_source(self._source_type(record))
                try:
                    target = await self._draw_target(record, source, method)
                except QRNGError as exc:
                    raise SourceUnavailable(f"não foi possível sortear o alvo: {exc}") from exc
            self._transition(
                record, State.TARGET_SELECTED, "TARGET_SELECTED",
                {"target": target, "method": str(method)},
                target=target, target_selected_at=format_ts(self._now()),
            )
            return record

    def start_intention(self, session_id: str) -> dict:
        record = self.get_record(session_id)
        require_state(State(record["state"]), State.TARGET_SELECTED)
        now = self._now()
        ends = now + timedelta(seconds=record["planned_duration_seconds"])
        self._transition(
            record, State.INTENTION_RUNNING, "INTENTION_STARTED",
            {"duration_seconds": record["planned_duration_seconds"], "ends_at": format_ts(ends),
             "neutral_period": record["module"] == str(Module.CONTROL)},
            intention_started_at=format_ts(now), intention_ends_at=format_ts(ends),
        )
        return record

    def complete_intention(self, session_id: str) -> dict:
        """M2/Controle → REVEAL_PENDING. M1 → registra conclusão e entra em GENERATING."""
        record = self.get_record(session_id)
        require_state(State(record["state"]), State.INTENTION_RUNNING)
        if record.get("intention_completed_at"):
            raise IllegalTransition("intenção já concluída")
        now = self._now()
        if now < parse_ts(record["intention_ends_at"]):
            remaining = (parse_ts(record["intention_ends_at"]) - now).total_seconds()
            raise TooEarly(f"o período de intenção ainda não terminou (faltam {remaining:.0f} s)")
        completed_at = format_ts(now)
        if Module(record["module"]) == Module.MODULE_1:
            self._log(record, "INTENTION_COMPLETED", {"completed_at": completed_at})
            self.index.update(session_id, intention_completed_at=completed_at)
            record["intention_completed_at"] = completed_at
            return self.begin_generation(session_id)
        self._transition(record, State.REVEAL_PENDING, "INTENTION_COMPLETED",
                         {"completed_at": completed_at}, intention_completed_at=completed_at)
        return record

    # -------------------------------------------------------------- revelação

    def _invalidate(self, record: dict, report: IntegrityReport) -> None:
        reasons = report.failures
        reason = "; ".join(reasons)[:2000]
        paths = self.paths(record["session_id"])
        if verify_chain(paths.audit).ok:
            self._log(record, "INTEGRITY_FAILED", {"checks": report.checks})
            self._transition(record, State.INVALIDATED, "SESSION_INVALIDATED", {"reasons": reasons},
                             invalid_reason=reason, integrity_status="FAILED")
        else:
            # Não é possível estender uma cadeia corrompida: registra no índice e no log global.
            check_transition(Module(record["module"]), State(record["state"]), State.INVALIDATED)
            self.global_log.append(record["session_id"], "SESSION_INVALIDATED", self._now(), {"reasons": reasons})
            self.index.update(record["session_id"], state=str(State.INVALIDATED), invalid_reason=reason,
                              integrity_status="FAILED", updated_at=format_ts(self._now()))
            record.update(state=str(State.INVALIDATED), invalid_reason=reason, integrity_status="FAILED")

    def reveal(self, session_id: str) -> dict:
        record = self.get_record(session_id)
        require_state(State(record["state"]), State.REVEAL_PENDING)
        paths = self.paths(session_id)
        if verify_chain(paths.audit).ok:
            self._log(record, "REVEAL_REQUESTED")
        report = verify_session(paths, record)
        if not report.ok:
            self._invalidate(record, report)
            return {"valid": False, "record": record, "integrity": report.to_dict()}

        self._log(record, "HASH_VERIFIED", {
            "preregistration_sha256": record["preregistration_sha256"],
            "manifest_sha256": record["manifest_sha256"],
            "events_sha256": record["events_sha256"],
        })
        head = verify_chain(paths.audit).head_hash
        self._log(record, "AUDIT_CHAIN_VERIFIED", {"head_hash": head})
        self._transition(record, State.REVEALED, "RESULT_REVEALED")

        prereg = report_service.load_json(paths.preregistration)
        manifest = report_service.load_json(paths.manifest)
        bits, _, _ = parse_events_csv(paths.events, session_id)
        entries = self._audit(session_id).entries()
        analysis = round_floats(build_analysis(
            preregistration=prereg,
            manifest=manifest,
            bits=bits,
            target=record["target"],
            timeline=timeline_from_audit(entries),
            hashes={
                "preregistration_sha256": record["preregistration_sha256"],
                "manifest_sha256": record["manifest_sha256"],
                "events_sha256": record["events_sha256"],
            },
            audit_head_hash=entries[-1]["hash_current_log_entry"],
            analyzed_timestamp=format_ts(self._now()),
        ))
        data = self.store.write_json_once(paths.analysis, analysis)
        self.store.make_read_only(paths)
        self._transition(
            record, State.ANALYZED, "ANALYSIS_COMPLETED", {"analysis_sha256": sha256_bytes(data)},
            observed_proportion=analysis["observed_proportion"], p_value=analysis["p_value"],
            significant=int(analysis["significant"]), integrity_status="OK",
        )
        html = report_service.render_report(paths, record, verify_session(paths, record))
        self.store.write_bytes_once(paths.report, html.encode("utf-8"))
        self._transition(record, State.COMPLETED, "SESSION_COMPLETED",
                         {"report_sha256": sha256_bytes(html.encode("utf-8"))})
        return {"valid": True, "record": record, "integrity": report.to_dict(), "analysis": analysis}

    # ---------------------------------------------------------- verificação

    def verify(self, session_id: str) -> IntegrityReport:
        record = self.get_record(session_id)
        state = State(record["state"])
        if state in (State.CREATED, State.PRE_REGISTERED, State.GENERATING, State.CANCELLED, State.QRNG_ERROR) or (
            state in (State.TARGET_SELECTED, State.INTENTION_RUNNING) and record["module"] == str(Module.MODULE_1)
        ):
            raise IllegalTransition("a verificação completa só existe depois que os dados são selados")
        complete = state in (State.REVEAL_PENDING, State.REVEALED, State.ANALYZED, State.COMPLETED, State.INVALIDATED)
        report = verify_session(self.paths(session_id), record, require_complete_timeline=complete)
        if state == State.COMPLETED:
            self.index.update(session_id, integrity_status="OK" if report.ok else "FAILED")
        return report

    def audit_head_hash(self, session_id: str) -> str | None:
        """Código de auditoria: hash da última entrada do audit.log.

        Anotado fora da máquina, permite ao verificador externo (--anchor)
        detectar uma reescrita completa da cadeia. Não depende dos dados.
        """
        entries = self._audit(session_id).entries()
        return entries[-1]["hash_current_log_entry"] if entries else None

    def read_analysis(self, session_id: str) -> dict:
        return report_service.load_json(self.paths(session_id).analysis)

    def data_dir(self) -> Path:
        return self.settings.data_dir
