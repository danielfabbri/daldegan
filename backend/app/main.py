"""Aplicação FastAPI do Daldegan.

Iniciar:  uvicorn backend.app.main:app --reload
Abrir:    http://127.0.0.1:8000
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .clock import Clock, SystemClock
from .config import Settings
from .errors import Blinded, IllegalTransition, NotFound, SealedSessionError, SourceUnavailable
from .qrng.factory import SourceFactory, default_factory
from .services.session_service import SessionService
from .version import SOFTWARE_VERSION

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

_ERROR_STATUS = {
    NotFound: 404,
    IllegalTransition: 409,
    SealedSessionError: 409,
    Blinded: 423,
    SourceUnavailable: 503,
}


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    source_factory: SourceFactory | None = None,
) -> FastAPI:
    settings = settings or Settings()
    clock = clock or SystemClock()
    service = SessionService(settings, clock, source_factory or default_factory(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.recover_interrupted()
        yield
        service.index.close()

    app = FastAPI(title="DALDEGAN", version=SOFTWARE_VERSION, lifespan=lifespan)
    app.state.service = service

    for exc_type, status in _ERROR_STATUS.items():
        def handler(request: Request, exc: Exception, status=status):
            return JSONResponse(status_code=status, content={"error": type(exc).__name__, "detail": str(exc)})

        app.add_exception_handler(exc_type, handler)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errors = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(status_code=400, content={"error": "ValidationError", "detail": errors})

    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")
    return app


app = create_app()
