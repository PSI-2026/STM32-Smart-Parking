"""Translate application and framework failures into the API error contract."""

import logging
import sqlite3

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from ..contracts.api import ApiError
from ..services.parking import BusinessFault

logger = logging.getLogger(__name__)


def error_response(status, code, message, *, retryable=False, headers=None):
    error = ApiError.model_validate({"error": {"code": code, "message": message, "retryable": retryable}})
    return JSONResponse(status_code=status, content=error.model_dump(by_alias=True),
                        headers={"Cache-Control": "no-store", **(headers or {})})


def register_http_handlers(application: FastAPI):
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
        if exc.status_code == 401:
            return error_response(401, "UNAUTHORIZED", "Autentificare necesară sau credențiale invalide.", headers=exc.headers)
        if exc.status_code == 403:
            return error_response(403, "FORBIDDEN", "Rolul sau profilul curent nu permite această acțiune.")
        if exc.status_code == 503:
            return error_response(503, "SERVICE_UNAVAILABLE", "Accesul API necesită configurarea credențialelor.")
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
