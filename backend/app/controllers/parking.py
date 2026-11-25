"""API v1 controllers: validate HTTP input and delegate to the application service."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response

from ..contracts.api import (
    ApiError, CommandRequest, CommandResult, EventPage, Health, Identifier,
    ParkingSession, ParkingSnapshot, SessionPage,
)
from ..services.parking import ParkingService
from .security import Principal, authorize_command, require_access

router = APIRouter(prefix="/api/v1")
errors = {code: {"model": ApiError} for code in (401, 403, 404, 409, 422, 500, 503)}
protected = [Depends(require_access)]


def parking_service(request: Request) -> ParkingService:
    """Resolve the service owned by this application's lifespan, never a global."""
    return request.app.state.parking


Service = Annotated[ParkingService, Depends(parking_service)]


@router.get("/health", response_model=Health, operation_id="healthCheck", tags=["Health"])
def health_check():
    return Health()


@router.get("/snapshot", response_model=ParkingSnapshot, operation_id="getSnapshot",
            dependencies=protected, responses={code: errors[code] for code in (401, 500, 503)})
def snapshot(request: Request, service: Service):
    return service.snapshot(transport=request.app.state.settings.transport)


@router.post("/commands", response_model=CommandResult, status_code=202, operation_id="submitCommand",
             responses={200: {"model": CommandResult}, **{code: errors[code] for code in (401, 403, 409, 422, 500, 503)}})
def submit_command(body: CommandRequest, response: Response, service: Service,
                   request: Request, principal: Annotated[Principal, Depends(require_access)]):
    if request.app.state.settings.hardware_profile == "hybrid-v1-readonly":
        raise HTTPException(403)
    authorize_command(principal, body.action.type)
    admission = service.admit(body)
    response.status_code = 200 if admission.replayed else 202
    return admission.result


@router.get("/commands/{commandId}", response_model=CommandResult, operation_id="getCommand",
            dependencies=protected, responses={code: errors[code] for code in (401, 404, 422, 500, 503)})
def get_command(service: Service, commandId: Annotated[Identifier, Path()]):
    return service.get_command(commandId)


@router.get("/sessions", response_model=SessionPage, operation_id="listSessions",
            dependencies=protected, responses={code: errors[code] for code in (401, 422, 500, 503)})
def sessions(service: Service, limit: Annotated[int, Query(ge=1, le=200)] = 50,
             cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None):
    return service.list_sessions(limit=limit, cursor=cursor)


@router.get("/sessions/{sessionId}", response_model=ParkingSession, operation_id="getSession",
            dependencies=protected, responses={code: errors[code] for code in (401, 404, 422, 500, 503)})
def get_session(service: Service, sessionId: Annotated[Identifier, Path()]):
    return service.get_session(sessionId)


@router.get("/events", response_model=EventPage, operation_id="listEvents",
            dependencies=protected, responses={code: errors[code] for code in (401, 422, 500, 503)})
def events(service: Service, limit: Annotated[int, Query(ge=1, le=200)] = 50,
           cursor: Annotated[str | None, Query(min_length=1, max_length=512)] = None):
    return service.list_events(limit=limit, cursor=cursor)
