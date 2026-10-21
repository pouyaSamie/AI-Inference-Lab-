"""FastAPI application factory with typed errors, auth and runtime lifecycle."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from lab_core.errors import ErrorBody, ErrorEnvelope, LabError
from lab_core.version import API_VERSION, CONTRACT_VERSION, SCHEMA_VERSION
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, get_settings
from .db import create_controller_engine, create_session_factory
from .routers import experiments, optimizer_internal, recipes, releases, system, workers
from .services.runtime import RuntimeScheduler

logger = logging.getLogger("lab_api")


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
    recovery_hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    envelope = ErrorEnvelope(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            recovery_hint=recovery_hint,
            request_id=request_id,
            details=details or {},
        )
    )
    return JSONResponse(envelope.model_dump(mode="json"), status_code=status_code)


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    _configure_logging(settings.log_level)
    owned_engine = engine is None and session_factory is None
    engine = engine or (None if session_factory is not None else create_controller_engine(settings))
    factory = session_factory or create_session_factory(engine)  # type: ignore[arg-type]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_directories()
        settings.validate_runtime()
        runtime = RuntimeScheduler(settings, factory)
        app.state.runtime = runtime
        await runtime.start()
        logger.info(
            "controller started",
            extra={"environment": settings.environment, "execution_mode": settings.execution_mode},
        )
        try:
            yield
        finally:
            await runtime.stop()
            if owned_engine and engine is not None:
                engine.dispose()
            logger.info("controller stopped")

    app = FastAPI(
        title="AI Inference Optimization Lab",
        version=SCHEMA_VERSION,
        description="Local-first AI inference optimization controller (Phases 2-8).",
        lifespan=lifespan,
        docs_url="/docs" if settings.document_openapi else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.document_openapi else None,
    )
    app.state.settings = settings
    app.state.session_factory = factory
    app.state.engine = engine
    app.state.runtime = None

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "Last-Event-ID",
            "X-Enrollment-Token",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID", "Idempotent-Replayed"],
    )

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming if incoming and len(incoming) <= 128 else f"req_{uuid.uuid4().hex}"
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "unhandled request failure", extra={"request_id": request_id, "path": request.url.path}
            )
            raise
        response.headers["X-Request-ID"] = request_id
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
            extra={"request_id": request_id},
        )
        return response

    @app.exception_handler(LabError)
    async def lab_error_handler(request: Request, exc: LabError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.http_status,
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            recovery_hint=exc.recovery_hint,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="request validation failed",
            details={"errors": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=f"HTTP_{exc.status_code}",
            message=str(exc.detail),
        )

    @app.exception_handler(Exception)
    async def unexpected_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled exception", extra={"request_id": getattr(request.state, "request_id", None)}
        )
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="an unexpected controller error occurred",
            retryable=True,
        )

    app.include_router(system.router)
    app.include_router(workers.router)
    app.include_router(experiments.router)
    app.include_router(optimizer_internal.router)
    app.include_router(recipes.router)
    app.include_router(releases.router)

    @app.get("/api/v1/meta", include_in_schema=False)
    def meta() -> dict[str, str]:
        return {
            "schema_version": SCHEMA_VERSION,
            "api_version": API_VERSION,
            "contract_version": CONTRACT_VERSION,
        }

    return app
