"""HTTP v1 application factory with explicit lifecycle and isolated test injection."""

import asyncio
from contextlib import asynccontextmanager
import logging
import sqlite3
from typing import Annotated

from fastapi import FastAPI, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException

from .contracts.api import ApiError, CommandRequest, CommandResult, EventPage, Health, Identifier, ParkingSession, ParkingSnapshot, SessionPage
from .parking import BusinessFault, ParkingService
from .settings import Settings
from .storage import Database
from .simulator import SimulatorRuntime
from .worker import business_worker

logger = logging.getLogger(__name__)


def error_response(status, code, message, *, retryable=False, headers=None):
    error = ApiError.model_validate({"error": {"code": code, "message": message, "retryable": retryable}})
    return JSONResponse(status_code=status, content=error.model_dump(by_alias=True),
                        headers={"Cache-Control": "no-store", **(headers or {})})


def create_app(settings: Settings | None = None, *, service: ParkingService | None = None):
    settings = settings or Settings()
    if service and (service.mode != settings.mode or service.hourly_rate_bani != settings.hourly_rate_bani):
        raise ValueError("Injected service must match mode and tariff configuration")

    @asynccontextmanager
    async def lifespan(application):
        active = service or await run_in_threadpool(lambda: ParkingService(
            Database(settings.database_path), mode=settings.mode, hourly_rate_bani=settings.hourly_rate_bani))
        await run_in_threadpool(active.recover)
        application.state.parking = active
        simulator = None
        if settings.mode == "simulation" and settings.simulator_enabled:
            simulator = SimulatorRuntime(active, step_delay_ms=settings.simulator_step_delay_ms,
                                         auto_passage=settings.simulator_auto_passage, transport=settings.transport)
            await run_in_threadpool(simulator.connect)
        application.state.simulator = simulator
        stop = asyncio.Event()
        task = asyncio.create_task(business_worker(active, stop, settings.worker_interval_seconds, simulator)) if settings.worker_enabled else None
        application.state.worker_task = task
        try:
            yield
        finally:
            stop.set()
            if task:
                await task
            if simulator:
                active.simulation_handler = None
                await simulator.adapter.close()

    application = FastAPI(title="STM32 Smart Parking API", description="Persistent parking API; simulated payments.",
                          version="0.1.0", lifespan=lifespan)

    @application.middleware("http")
    async def no_cache(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(BusinessFault)
    async def business_error(request, exc):
        code = exc.detail.code
        status = {"VALIDATION_ERROR": 422, "NOT_FOUND": 404, "IDEMPOTENCY_CONFLICT": 409,
                  "DATA_UNAVAILABLE": 503, "SERVICE_UNAVAILABLE": 503,
                  "DEVICE_INCOMPATIBLE": 503, "DEVICE_TIMEOUT": 503, "INTERNAL_ERROR": 500}.get(code, 409)
        return error_response(status, code, exc.detail.message, retryable=exc.detail.retryable)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error_response(422, "VALIDATION_ERROR", "Corpul cererii sau parametrii nu respectă schema API.")

    @application.exception_handler(HTTPException)
    async def http_error(request, exc):
        if exc.status_code == 400:
            # FastAPI wraps body-decoding failures (including invalid Unicode)
            # in HTTPException(400), before RequestValidationError is produced.
            return error_response(422, "VALIDATION_ERROR", "Corpul cererii nu poate fi decodat.")
        if exc.status_code == 404:
            return error_response(404, "NOT_FOUND", "Resursa nu există.", headers=exc.headers)
        if exc.status_code == 405:
            return error_response(405, "VALIDATION_ERROR", "Metodă HTTP nepermisă.", headers=exc.headers)
        return error_response(exc.status_code, "VALIDATION_ERROR", "Cerere HTTP invalidă.", headers=exc.headers)

    @application.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        busy = getattr(exc, "sqlite_errorcode", 0) & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        if busy:
            return error_response(503, "SERVICE_UNAVAILABLE", "Baza de date este ocupată; repetă aceeași cerere.", retryable=True)
        logger.exception("Database operation failed")
        return error_response(500, "INTERNAL_ERROR", "Operația nu a putut fi finalizată; repetă aceeași cerere.", retryable=True)

    @application.exception_handler(Exception)
    async def internal_error(request, exc):
        logger.error("Unhandled API error", exc_info=exc)
        return error_response(500, "INTERNAL_ERROR", "Eroare internă a serviciului.", retryable=True)

    def parking(request: Request):
        return request.app.state.parking

    errors = {code: {"model": ApiError} for code in (404, 409, 422, 500, 503)}

    @application.get("/api/v1/health", response_model=Health, operation_id="healthCheck", tags=["Health"])
    def health_check():
        return Health()

    @application.get("/api/v1/snapshot", response_model=ParkingSnapshot, operation_id="getSnapshot",
                     responses={code: errors[code] for code in (500, 503)})
    def snapshot(request: Request):
        return parking(request).snapshot(transport=settings.transport)

    @application.post("/api/v1/commands", response_model=CommandResult, status_code=202, operation_id="submitCommand",
                      responses={200: {"model": CommandResult}, **{code: errors[code] for code in (409, 422, 500, 503)}})
    def submit_command(body: CommandRequest, request: Request, response: Response):
        admission = parking(request).admit(body)
        response.status_code = 200 if admission.replayed else 202
        return admission.result

    @application.get("/api/v1/commands/{commandId}", response_model=CommandResult, operation_id="getCommand",
                     responses={code: errors[code] for code in (404, 422, 500, 503)})
    def get_command(request: Request, commandId: Annotated[Identifier, Path()]):
        return parking(request).get_command(commandId)

    @application.get("/api/v1/sessions", response_model=SessionPage, operation_id="listSessions",
                     responses={code: errors[code] for code in (422, 500, 503)})
    def sessions(request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                 cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None):
        return parking(request).list_sessions(limit=limit, cursor=cursor)

    @application.get("/api/v1/sessions/{sessionId}", response_model=ParkingSession, operation_id="getSession",
                     responses={code: errors[code] for code in (404, 422, 500, 503)})
    def get_session(request: Request, sessionId: Annotated[Identifier, Path()]):
        return parking(request).get_session(sessionId)

    @application.get("/api/v1/events", response_model=EventPage, operation_id="listEvents",
                     responses={code: errors[code] for code in (422, 500, 503)})
    def events(request: Request, limit: Annotated[int, Query(ge=1, le=200)] = 50,
               cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None):
        return parking(request).list_events(limit=limit, cursor=cursor)

    return application


app = create_app()
