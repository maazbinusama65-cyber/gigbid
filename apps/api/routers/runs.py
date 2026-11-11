"""Agent runs: list, detail, SSE stream, trace."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.runs import RunDetail, RunList, TraceResponse
from apps.api.services import Services
from apps.api.streaming import sse_response

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=RunList)
async def list_runs(
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> RunList:
    return await services.list_runs(user)


@router.get("/{run_id}", response_model=RunDetail)
async def get_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> RunDetail:
    return await services.get_run(user, run_id)


@router.get(
    "/{run_id}/stream",
    summary="Server-Sent Events: live node-by-node progress",
    response_description="text/event-stream of RunEvent JSON objects",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_run(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
):
    await services.get_run(user, run_id)  # 404 (also for other tenants' runs) before the stream opens
    return sse_response(services.stream_run(user, run_id))


@router.get("/{run_id}/trace", response_model=TraceResponse)
async def get_trace(
    run_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> TraceResponse:
    return await services.get_trace(user, run_id)
