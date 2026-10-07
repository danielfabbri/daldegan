"""Rotas HTTP (SPEC §9). Não existe rota de DELETE nem de edição."""

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..audit.hashing import format_ts
from ..models.api import CreateSessionRequest, CumulativeRequest, SelectTargetRequest
from ..models.enums import Module, State
from ..services import blind_view, history_service
from ..services.session_service import SessionService
from ..statistics.binomial import P_VALUE_EXPLANATION, minimum_detectable_deviation_pp
from ..version import PROTOCOL_VERSION, SOFTWARE_VERSION

router = APIRouter(prefix="/api")


def _svc(request: Request) -> SessionService:
    return request.app.state.service


def _view(svc: SessionService, record: dict) -> dict:
    view = blind_view.serialize(record, svc.clock, svc.settings.show_full_hash)
    view["audit_code"] = svc.audit_head_hash(record["session_id"])
    view["session_path"] = str(svc.paths(record["session_id"]).root)
    return view


# ------------------------------------------------------------------ sistema

@router.get("/system/info")
def system_info(request: Request):
    svc = _svc(request)
    s = svc.settings
    return {
        "software_version": SOFTWARE_VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "server_time": format_ts(svc.clock.now()),
        "quantum_source": {
            "name": "ANU Quantum Numbers (AQN)",
            "endpoint": s.qrng_endpoint,
            "data_type": s.qrng_data_type,
            "api_key_configured": bool(s.qrng_api_key),
        },
        "show_full_hash": s.show_full_hash,
        "p_value_explanation": P_VALUE_EXPLANATION,
    }


@router.get("/planning")
def planning(request: Request, event_count: int, test_mode: bool = False):
    """Informação pré-experimento, calculada sem nenhum dado."""
    svc = _svc(request)
    return {
        "event_count": event_count,
        "minimum_detectable_deviation_pp": minimum_detectable_deviation_pp(max(1, event_count)),
        "qrng_requests": svc.requests_needed(event_count, test_mode),
    }


# ------------------------------------------------------------------ sessões

@router.post("/sessions", status_code=201)
async def create_session(request: Request, body: CreateSessionRequest):
    svc = _svc(request)
    record = await svc.create_session(body)
    _, sha = svc.preregistration(record["session_id"])
    return {"session": _view(svc, record), "preregistration_sha256": sha,
            "message": "Seu protocolo foi registrado."}


@router.get("/sessions/{session_id}")
def get_session(request: Request, session_id: str):
    svc = _svc(request)
    return _view(svc, svc.get_record(session_id))


@router.get("/sessions/{session_id}/preregistration")
def get_preregistration(request: Request, session_id: str):
    data, sha = _svc(request).preregistration(session_id)
    return Response(
        content=data,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{session_id}-preregistration.json"',
                 "X-SHA256": sha},
    )


@router.post("/sessions/{session_id}/generate", status_code=202)
def generate(request: Request, session_id: str, background: BackgroundTasks):
    svc = _svc(request)
    record = svc.begin_generation(session_id)
    background.add_task(svc.run_generation, session_id)
    return _view(svc, record)


@router.post("/sessions/{session_id}/target")
async def select_target(request: Request, session_id: str, body: SelectTargetRequest):
    svc = _svc(request)
    record = await svc.select_target(session_id, body)
    return _view(svc, record)


@router.post("/sessions/{session_id}/intention/start")
def start_intention(request: Request, session_id: str):
    svc = _svc(request)
    return _view(svc, svc.start_intention(session_id))


@router.post("/sessions/{session_id}/intention/complete")
def complete_intention(request: Request, session_id: str, background: BackgroundTasks):
    svc = _svc(request)
    record = svc.complete_intention(session_id)
    if record["module"] == str(Module.MODULE_1) and record["state"] == str(State.GENERATING):
        background.add_task(svc.run_generation, session_id)
    return _view(svc, record)


@router.post("/sessions/{session_id}/cancel")
def cancel(request: Request, session_id: str):
    svc = _svc(request)
    return _view(svc, svc.cancel(session_id))


@router.post("/sessions/{session_id}/reveal")
def reveal(request: Request, session_id: str):
    svc = _svc(request)
    out = svc.reveal(session_id)
    body = {"valid": out["valid"], "session": _view(svc, out["record"]), "integrity": out["integrity"]}
    if out["valid"]:
        body["analysis"] = out["analysis"]
    else:
        body["message"] = "SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada."
    return body


@router.get("/sessions/{session_id}/result")
def get_result(request: Request, session_id: str):
    return history_service.result(_svc(request), session_id)


@router.get("/sessions/{session_id}/verify")
def verify(request: Request, session_id: str):
    svc = _svc(request)
    report = svc.verify(session_id)
    return {"session_id": session_id, **report.to_dict(),
            "external_command": f"python scripts/verify_session.py {svc.paths(session_id).root}"}


@router.get("/sessions/{session_id}/report.html", response_class=HTMLResponse)
def report(request: Request, session_id: str):
    return HTMLResponse(history_service.report_html(_svc(request), session_id))


@router.get("/sessions/{session_id}/export.json")
def export(request: Request, session_id: str):
    return JSONResponse(
        history_service.export_json(_svc(request), session_id),
        headers={"Content-Disposition": f'attachment; filename="{session_id}.json"'},
    )


@router.get("/sessions/{session_id}/events.csv")
def events(request: Request, session_id: str):
    return Response(
        history_service.events_csv(_svc(request), session_id),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{session_id}-events.csv"'},
    )


# ------------------------------------------------------------------ histórico

@router.get("/history")
def history(request: Request, test_mode: bool = False):
    return history_service.history(_svc(request), test_mode)


@router.get("/history.csv")
def history_csv(request: Request, test_mode: bool = False):
    name = "historico-teste.csv" if test_mode else "historico.csv"
    return Response(history_service.history_csv(_svc(request), test_mode), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ------------------------------------------------------------------ análise

@router.get("/analysis/protocols")
def protocols(request: Request):
    return history_service.list_protocols(_svc(request))


@router.post("/analysis/cumulative")
def cumulative(request: Request, body: CumulativeRequest):
    return history_service.cumulative(_svc(request), body.mode, body.fingerprint, body.session_ids)



