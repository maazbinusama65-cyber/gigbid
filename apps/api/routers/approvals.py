"""Approval queue: every send / spend waits here until a human decides (R4)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException

from agent.handoffs import ApprovalDecision
from apps.api.auth.deps import CurrentUser, get_current_user, get_services
from apps.api.schemas.approvals import ApprovalList, DecisionResult
from apps.api.services import Services

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=ApprovalList)
async def list_approvals(
    status: Literal["pending", "approved", "edited", "rejected"] | None = None,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> ApprovalList:
    return await services.list_approvals(user, status)


@router.post("/{approval_id}/decision", response_model=DecisionResult)
async def decide_approval(
    approval_id: str,
    decision: ApprovalDecision,
    user: CurrentUser = Depends(get_current_user),
    services: Services = Depends(get_services),
) -> DecisionResult:
    if decision.action == "edit" and not (decision.edited_text and decision.edited_text.strip()):
        raise HTTPException(status_code=422, detail="edited_text is required when action is 'edit'")
    if decision.action == "reject" and not (decision.reason and decision.reason.strip()):
        raise HTTPException(status_code=422, detail="reason is required when action is 'reject'")
    return await services.decide_approval(user, approval_id, decision)
