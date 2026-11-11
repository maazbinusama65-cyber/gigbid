"""Health, including marketplace reachability (drives the UI's degraded banner)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.auth.deps import get_config, get_services
from apps.api.config import AppConfig
from apps.api.schemas.common import HealthResponse
from apps.api.services import Services

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    cfg: AppConfig = Depends(get_config),
    services: Services = Depends(get_services),
) -> HealthResponse:
    marketplace = await services.marketplace_health()
    return HealthResponse(
        status="ok" if marketplace.ok else "degraded",
        services_mode=cfg.services_mode,
        marketplace=marketplace,
    )
