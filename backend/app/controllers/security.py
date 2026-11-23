"""Explicit bearer credentials and permissions at the HTTP boundary."""

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False, scheme_name="ParkingBearer")


@dataclass(frozen=True)
class Principal:
    role: str


def require_access(request: Request,
                   credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> Principal:
    settings = request.app.state.settings
    configured = [(role, value.get_secret_value()) for role, value in (
        ("viewer", settings.viewer_token), ("operator", settings.operator_token), ("admin", settings.admin_token)) if value is not None]
    if credentials is not None:
        for role, token in configured:
            if compare_digest(credentials.credentials.encode("utf-8"), token.encode("utf-8")):
                return Principal(role)
        raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
    if settings.mode == "simulation" and settings.allow_anonymous_simulation:
        return Principal("admin")
    if not configured:
        raise HTTPException(503)
    raise HTTPException(401, headers={"WWW-Authenticate": "Bearer"})


def authorize_command(principal: Principal, action_type: str):
    required = "operator" if action_type in ("enter", "pay", "exit") else "admin"
    if principal.role == "viewer" or (required == "admin" and principal.role != "admin"):
        raise HTTPException(403)
