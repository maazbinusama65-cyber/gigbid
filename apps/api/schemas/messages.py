"""Client thread models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["question", "negotiation", "interview_request", "scam_signal", "other"]
ThreadStatus = Literal["needs_reply", "awaiting_client", "interview_scheduled", "closed"]


class ThreadSummary(BaseModel):
    thread_id: str
    client_name: str
    job_title: str
    last_message: str
    last_message_at: str
    unread: bool = False
    intent: Intent = "other"
    status: ThreadStatus = "needs_reply"
    has_suggested_reply: bool = False
    injection_detected: bool = False


class ThreadList(BaseModel):
    threads: list[ThreadSummary]
    marketplace_degraded: bool = False


class ChatMessage(BaseModel):
    message_id: str
    sender: Literal["client", "freelancer"]
    body: str
    ts: str
    flagged: bool = Field(default=False, description="contains a planted instruction or scam signal")


class SuggestedReply(BaseModel):
    approval_id: str
    text: str
    intent: Intent = "other"
    rationale: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class InterviewSlot(BaseModel):
    slot_id: str
    start: str
    end: str
    label: str


class ThreadDetail(BaseModel):
    thread: ThreadSummary
    messages: list[ChatMessage]
    suggested_reply: SuggestedReply | None = None
    slots: list[InterviewSlot] = Field(default_factory=list)
    job_id: str | None = None
    safety_note: str = ""


class MessageDecisionRequest(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = Field(default=None, max_length=5000)
    reason: str | None = Field(default=None, max_length=500)
    slot_id: str | None = None


class MessageDecisionResult(BaseModel):
    thread_id: str
    status: Literal["sent", "queued", "rejected"]
    interview_hold: InterviewSlot | None = None
    message: str = ""
