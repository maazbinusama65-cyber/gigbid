"""Registration, login, logout, current user."""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.auth.deps import CurrentUser, get_config, get_current_user, get_db
from apps.api.auth.passwords import DUMMY_HASH, hash_password, verify_password
from apps.api.auth.sessions import create_session, revoke_session
from apps.api.config import AppConfig
from apps.api.db import SessionRow, UserRow
from apps.api.errors import Conflict, TooManyRequests, Unauthorized
from apps.api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from apps.api.schemas.common import OkResponse

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("apps.api.auth")

_FAIL_WINDOW_S = 300
_failures: dict[str, deque[float]] = defaultdict(deque)


def _too_many(key: str, limit: int) -> bool:
    now = time.monotonic()
    bucket = _failures[key]
    while bucket and now - bucket[0] > _FAIL_WINDOW_S:
        bucket.popleft()
    return len(bucket) >= limit


def _to_out(user: UserRow) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name,
        persona_id=user.persona_id, onboarded=user.onboarded,
    )


def _token_response(db: Session, user: UserRow, cfg: AppConfig) -> TokenResponse:
    token, row = create_session(db, user.id, cfg.session_ttl_hours)
    return TokenResponse(access_token=token, expires_at=row.expires_at.isoformat(), user=_to_out(user))


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db), cfg: AppConfig = Depends(get_config)) -> TokenResponse:
    email = body.email.strip().lower()
    if db.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none():
        raise Conflict("An account with this e-mail already exists")
    user = UserRow(
        email=email,
        display_name=body.display_name.strip() or email.split("@")[0],
        password_hash=hash_password(body.password, cfg.scrypt_n),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("An account with this e-mail already exists") from exc
    log.info("user registered id=%s", user.id)
    return _token_response(db, user, cfg)


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest, request: Request, db: Session = Depends(get_db), cfg: AppConfig = Depends(get_config)
) -> TokenResponse:
    email = body.email.strip().lower()
    client_ip = request.client.host if request.client else "?"
    key = f"{client_ip}|{email}"
    if _too_many(key, cfg.login_max_failures):
        raise TooManyRequests("Too many failed attempts; try again in a few minutes")
    user = db.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok:
        _failures[key].append(time.monotonic())
        raise Unauthorized("Incorrect e-mail or password")
    _failures.pop(key, None)
    log.info("login ok user=%s", user.id)
    return _token_response(db, user, cfg)


@router.get("/me", response_model=UserOut)
def get_me(user: CurrentUser = Depends(get_current_user)) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name,
        persona_id=user.persona_id, onboarded=user.onboarded,
    )


@router.post("/logout", response_model=OkResponse)
def logout(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OkResponse:
    row = db.execute(
        select(SessionRow).where(SessionRow.id == user.session_id, SessionRow.user_id == user.id)
    ).scalar_one_or_none()
    if row:
        revoke_session(db, row)
    return OkResponse(detail="signed out")

