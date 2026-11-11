"""Settings, memory viewer (list + delete what GigBid learned) and connected marketplace accounts."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import token_store
from apps.api.auth.crypto import TokenCipher
from apps.api.auth.deps import CurrentUser, get_cipher, get_current_user, get_db, get_services
from apps.api.errors import NotFound
from apps.api.schemas.common import OkResponse
from apps.api.schemas.settings import (
    Connection,
    ConnectionList,
    ConnectRequest,
    MemoryList,
    UserSettings,
    UserSettingsUpdate,
)
from apps.api.services import Services

router = APIRouter(tags=["settings"])
log = logging.getLogger("apps.api.settings")


@router.get("/settings", response_model=UserSettings)
async def get_settings(
    user: CurrentUser = Depends(get_current_user), services: Services = Depends(get_services)
) -> UserSettings:
    return await services.get_settings(user)


@router.put("/settings", response_model=UserSettings)
async def update_settings(
    body: UserSettingsUpdate,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> UserSettings:
    return await services.update_settings(user, body)


@router.get("/memory", response_model=MemoryList)
async def list_memory(
    user: CurrentUser = Depends(get_current_user), services: Services = Depends(get_services)
) -> MemoryList:
    return await services.list_memory(user)


@router.delete("/memory/{memory_id}", response_model=OkResponse)
async def delete_memory(
    memory_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> OkResponse:
    await services.delete_memory(user, memory_id)
    return OkResponse(detail="forgotten")


def _connections(db: Session, user_id: str) -> ConnectionList:
    rows = {r.provider: r for r in token_store.list_connections(db, user_id)}
    return ConnectionList(
        connections=[
            Connection(
                provider=p,  # type: ignore[arg-type]
                connected=p in rows,
                connected_at=rows[p].created_at.isoformat() if p in rows else None,
                scopes=rows[p].scopes if p in rows else "",
            )
            for p in token_store.PROVIDERS
        ]
    )


@router.get("/settings/connections", response_model=ConnectionList)
def list_connections(
    user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConnectionList:
    return _connections(db, user.id)


@router.put("/settings/connections/{provider}", response_model=ConnectionList)
def connect_account(
    provider: str,
    body: ConnectRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    cipher: TokenCipher = Depends(get_cipher),
) -> ConnectionList:
    if provider not in token_store.PROVIDERS:
        raise NotFound(f"Unknown provider {provider!r}")
    token_store.save_token(db, cipher, user.id, provider, body.access_token, body.refresh_token, body.scopes)
    log.info("oauth connected user=%s provider=%s", user.id, provider)  # token deliberately not logged
    return _connections(db, user.id)


@router.delete("/settings/connections/{provider}", response_model=ConnectionList)
def disconnect_account(
    provider: str, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConnectionList:
    if provider not in token_store.PROVIDERS:
        raise NotFound(f"Unknown provider {provider!r}")
    token_store.delete_token(db, user.id, provider)
    return _connections(db, user.id)
