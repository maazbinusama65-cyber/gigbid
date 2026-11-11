"""Opaque session tokens: random 256-bit token, only its SHA-256 is persisted."""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db import SessionRow, UserRow, utcnow


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: str, ttl_hours: int) -> tuple[str, SessionRow]:
    token = secrets.token_urlsafe(32)
    row = SessionRow(
        user_id=user_id,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    db.add(row)
    db.commit()
    return token, row


def resolve_session(db: Session, token: str) -> tuple[UserRow, SessionRow] | None:
    row = db.execute(
        select(SessionRow).where(SessionRow.token_hash == hash_token(token))
    ).scalar_one_or_none()
    if row is None or row.revoked:
        return None
    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    if expires <= utcnow():
        return None
    user = db.execute(select(UserRow).where(UserRow.id == row.user_id)).scalar_one_or_none()
    if user is None:
        return None
    return user, row


def revoke_session(db: Session, session: SessionRow) -> None:
    session.revoked = True
    db.add(session)
    db.commit()
