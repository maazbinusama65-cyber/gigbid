"""Kanban pipeline."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.pipeline import PipelineBoard
from apps.api.services import Services

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.get("", response_model=PipelineBoard)
async def pipeline_board(
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> PipelineBoard:
    return await services.pipeline_board(user)
