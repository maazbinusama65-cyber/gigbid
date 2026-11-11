"""Approval inbox models. ``ApprovalRequest`` / ``ApprovalDecision`` come from agent.handoffs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent.handoffs import ApprovalDecision, ApprovalRequest

ApprovalStatus = Literal["pending", "approved", "edited", "rejected"]

__all__ = [
    "ApprovalDecision",
    "ApprovalItem",
    "ApprovalList",
    "ApprovalRequest",
    "DecisionResult",
    "ApprovalStatus",
]


class ApprovalItem(BaseModel):
    approval_id: str
    status: ApprovalStatus = "pending"
    created_at: str
    decided_at: str | None = None
    run_id: str | None = None
    title: str = ""
    request: ApprovalRequest
    decision: ApprovalDecision | None = None


class ApprovalList(BaseModel):
    approvals: list[ApprovalItem]
    pending_count: int = 0


class DecisionResult(BaseModel):
    approval_id: str
    status: ApprovalStatus
    run_id: str | None = None
    submitted: bool = False
    queued: bool = Field(default=False, description="true when the marketplace was unavailable and the send is retried")
    proposal_id: str | None = None
    connects_spent: int = 0
    message: str = ""
