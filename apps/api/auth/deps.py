"""FastAPI dependencies: DB session, current user, services."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from apps.api.auth.crypto import TokenCipher
from apps.api.auth.sessions import resolve_session
from apps.api.config import AppConfig
from apps.api.errors import Unauthorized

if TYPE_CHECKING:
    from apps.api.services import Services

bearer_scheme = HTTPBearer(auto_error=False, description="Opaque session token from /api/auth/login")


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    display_name: str
    persona_id: str | None
    onboarded: bool
    session_id: str = ""


def get_db(request: Request) -> Iterator[Session]:
    db: Session = request.app.state.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_cipher(request: Request) -> TokenCipher:
    return request.app.state.cipher


def get_services(request: Request) -> Services:
    return request.app.state.services


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise Unauthorized("Missing bearer token")
    resolved = resolve_session(db, creds.credentials)
    if resolved is None:
        raise Unauthorized("Invalid or expired session")
    user, session = resolved
    return CurrentUser(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        persona_id=user.persona_id,
        onboarded=user.onboarded,
        session_id=session.id,
    )
