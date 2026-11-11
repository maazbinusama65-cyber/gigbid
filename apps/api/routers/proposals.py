"""Proposal studio."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.proposals import ProposalStudio, RegenerateRequest
from apps.api.services import Services

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("/{job_id}", response_model=ProposalStudio)
async def get_proposal_studio(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> ProposalStudio:
    return await services.get_proposal_studio(user, job_id)


@router.post("/{job_id}/regenerate", response_model=ProposalStudio)
async def regenerate_paragraph(
    job_id: str,
    body: RegenerateRequest,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> ProposalStudio:
    return await services.regenerate_paragraph(user, job_id, body)
