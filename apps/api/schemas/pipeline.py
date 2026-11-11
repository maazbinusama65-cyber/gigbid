"""Kanban pipeline models."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PipelineStage = Literal["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]
STAGES: tuple[PipelineStage, ...] = (
    "drafted", "submitted", "viewed", "replied", "interview", "hired", "lost",
)


class PipelineCard(BaseModel):
    proposal_id: str
    job_id: str
    title: str
    client_name: str = ""
    stage: PipelineStage
    bid_amount: float | None = None
    currency: str = "USD"
    connects_spent: int = 0
    updated_at: str
    last_event: str = ""
    thread_id: str | None = None


class PipelineColumn(BaseModel):
    stage: PipelineStage
    label: str
    cards: list[PipelineCard] = Field(default_factory=list)


class MarketplaceEvent(BaseModel):
    event_id: str
    ts: str
    type: Literal["viewed", "replied", "interview", "hired", "lost", "message"]
    proposal_id: str | None = None
    thread_id: str | None = None
    summary: str = ""


class PipelineBoard(BaseModel):
    columns: list[PipelineColumn]
    recent_events: list[MarketplaceEvent] = Field(default_factory=list)
    marketplace_degraded: bool = False
    updated_at: str
