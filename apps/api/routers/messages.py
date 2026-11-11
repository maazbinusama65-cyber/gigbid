"""Client threads with suggested replies; nothing is sent without approval."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.messages import (
    MessageDecisionRequest,
    MessageDecisionResult,
    ThreadDetail,
    ThreadList,
)
from apps.api.services import Services

router = APIRouter(prefix="/messages", tags=["messages"])


@router.get("", response_model=ThreadList)
async def list_threads(
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> ThreadList:
    return await services.list_threads(user)


@router.get("/{thread_id}", response_model=ThreadDetail)
async def get_thread(
    thread_id: str,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> ThreadDetail:
    return await services.get_thread(user, thread_id)


@router.post("/{thread_id}/decision", response_model=MessageDecisionResult)
async def decide_message(
    thread_id: str,
    body: MessageDecisionRequest,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> MessageDecisionResult:
    if body.action == "edit" and not (body.edited_text and body.edited_text.strip()):
        raise HTTPException(status_code=422, detail="edited_text is required when action is 'edit'")
    if body.action == "reject" and not (body.reason and body.reason.strip()):
        raise HTTPException(status_code=422, detail="reason is required when action is 'reject'")
    return await services.decide_message(user, thread_id, body)
