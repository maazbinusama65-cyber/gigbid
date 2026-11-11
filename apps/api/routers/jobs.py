"""Job inbox, detail, analyze, skip."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query

from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.jobs import (
    AnalyzeResponse,
    JobDetail,
    JobListResponse,
    SkipRequest,
    SkipResponse,
)
from apps.api.services import Services

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=JobListResponse)
async def list_jobs(
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=80),
    min_fit: float | None = Query(default=None, ge=0, le=1),
    include_skipped: bool = False,
    sort: Literal["fit", "posted", "budget"] = "fit",
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> JobListResponse:
    return await services.list_jobs(
        user, q=q, category=category, min_fit=min_fit, include_skipped=include_skipped, sort=sort
    )


@router.get("/{job_id}", response_model=JobDetail)
async def get_job_detail(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> JobDetail:
    return await services.get_job_detail(user, job_id)


@router.post("/{job_id}/analyze", response_model=AnalyzeResponse, status_code=202)
async def analyze_job(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> AnalyzeResponse:
    return await services.analyze_job(user, job_id)


@router.post("/{job_id}/skip", response_model=SkipResponse)
async def skip_job(
    job_id: str,
    body: SkipRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> SkipResponse:
    return await services.skip_job(user, job_id, (body.reason if body else ""))
