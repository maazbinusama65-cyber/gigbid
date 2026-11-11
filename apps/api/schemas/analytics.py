"""Analytics models. ``is_sample`` MUST be true whenever numbers are fixtures, never real outcomes."""
from __future__ import annotations

from pydantic import BaseModel, Field


class CategoryStat(BaseModel):
    category: str
    proposals_sent: int
    replies: int
    hires: int
    reply_rate: float = Field(ge=0, le=1)
    hire_rate: float = Field(ge=0, le=1)


class ConnectsPoint(BaseModel):
    period: str
    connects_spent: int
    replies: int
    hires: int


class RejectionReason(BaseModel):
    reason: str
    count: int


class CostLatency(BaseModel):
    proposals_measured: int
    avg_cost_usd_per_proposal: float
    p50_latency_s: float
    p95_latency_s: float
    avg_cost_usd_per_job_analysed: float
    p95_latency_s_per_job_analysed: float


class AnalyticsSummary(BaseModel):
    is_sample: bool
    sample_note: str = ""
    period_label: str = ""
    totals: dict[str, float] = Field(default_factory=dict)
    by_category: list[CategoryStat]
    connects_vs_outcomes: list[ConnectsPoint]
    cost_latency: CostLatency
    top_rejection_reasons: list[RejectionReason]
