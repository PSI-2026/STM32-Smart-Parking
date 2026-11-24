"""Read cached v1 diagnostics; a GET never performs I/O on the serial port."""

from fastapi import APIRouter, Depends, Request

from ..contracts.api import ApiError
from ..contracts.legacy import LegacyTelemetry
from ..legacy import unavailable_telemetry
from .security import require_access

router = APIRouter(prefix="/api/v1")


@router.get("/diagnostics/legacy", response_model=LegacyTelemetry, operation_id="getLegacyTelemetry",
            dependencies=[Depends(require_access)], responses={code: {"model": ApiError} for code in (401, 500, 503)})
def legacy_telemetry(request: Request):
    reader = request.app.state.legacy_reader
    if reader is not None:
        return reader.snapshot()
    settings = request.app.state.settings
    return unavailable_telemetry(settings.legacy_unit_id, settings.legacy_stale_after_ms,
        selected=settings.mode == "hardware" and settings.hardware_profile == "hybrid-v1-readonly",
        enabled=False)
