"""Encrypted, tenant-scoped OAuth token store. Every function takes user_id and filters on it."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.auth.crypto import TokenCipher
from apps.api.db import OAuthTokenRow, utcnow

PROVIDERS = ("gigsim", "upwork")


def save_token(
    db: Session,
    cipher: TokenCipher,
    user_id: str,
    provider: str,
    access_token: str,
    refresh_token: str | None = None,
    scopes: str = "",
) -> OAuthTokenRow:
    row = db.execute(
        select(OAuthTokenRow).where(
            OAuthTokenRow.user_id == user_id, OAuthTokenRow.provider == provider
        )
    ).scalar_one_or_none()
    if row is None:
        row = OAuthTokenRow(user_id=user_id, provider=provider, access_token_enc=b"")
    row.access_token_enc = cipher.encrypt(access_token)
    row.refresh_token_enc = cipher.encrypt(refresh_token) if refresh_token else None
    row.scopes = scopes
    row.created_at = utcnow()
    db.add(row)
    db.commit()
    return row


def get_access_token(db: Session, cipher: TokenCipher, user_id: str, provider: str) -> str | None:
    row = db.execute(
        select(OAuthTokenRow).where(
            OAuthTokenRow.user_id == user_id, OAuthTokenRow.provider == provider
        )
    ).scalar_one_or_none()
    return cipher.decrypt(row.access_token_enc) if row else None


def list_connections(db: Session, user_id: str) -> list[OAuthTokenRow]:
    return list(
        db.execute(select(OAuthTokenRow).where(OAuthTokenRow.user_id == user_id)).scalars()
    )


def delete_token(db: Session, user_id: str, provider: str) -> bool:
    result = db.execute(
        delete(OAuthTokenRow).where(
            OAuthTokenRow.user_id == user_id, OAuthTokenRow.provider == provider
        )
    )
    db.commit()
    return (result.rowcount or 0) > 0
