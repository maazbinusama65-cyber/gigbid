"""Analytics."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.analytics import AnalyticsSummary
from apps.api.services import Services

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("", response_model=AnalyticsSummary)
async def analytics_summary(
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> AnalyticsSummary:
    return await services.analytics_summary(user)
