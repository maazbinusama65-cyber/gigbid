"""Job inbox and job detail models (agent objects are reused from agent.handoffs)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from agent.handoffs import (
    BidDecision,
    EvidenceRef,
    FitReport,
    JobSpec,
    PriceQuote,
    RiskReport,
)

Recommendation = Literal["bid", "watch", "skip"]
JobStatus = Literal["new", "analyzing", "analyzed", "drafted", "skipped"]


class JobBudget(BaseModel):
    type: Literal["fixed", "hourly"] = "fixed"
    min: float | None = None
    max: float | None = None
    currency: str = "USD"


class JobPosting(BaseModel):
    """The raw (untrusted) job post as served by the marketplace."""

    job_id: str
    client_id: str
    title: str
    description: str
    category: str
    required_skills: list[str] = Field(default_factory=list)
    budget: JobBudget = Field(default_factory=JobBudget)
    duration_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    posted_at: str
    connects_cost: int = 0


class JobSummary(BaseModel):
    """One inbox row."""

    job_id: str
    title: str
    category: str
    client_name: str = ""
    budget: JobBudget = Field(default_factory=JobBudget)
    posted_at: str
    fit_score: float | None = Field(default=None, ge=0, le=1)
    risk_score: float | None = Field(default=None, ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list)
    is_scam: bool = False
    injection_detected: bool = False
    recommendation: Recommendation | None = None
    suggested_price: float | None = None
    connects_cost: int = 0
    status: JobStatus = "new"
    top_skills: list[str] = Field(default_factory=list)
    run_id: str | None = None


class JobListResponse(BaseModel):
    jobs: list[JobSummary]
    total: int
    marketplace_degraded: bool = False
    categories: list[str] = Field(default_factory=list)


class ClientSummary(BaseModel):
    client_id: str
    name: str
    industry: str = ""
    payment_verified: bool = False
    total_spent: float = 0
    hire_rate: float = 0
    avg_rating: float | None = None
    jobs_posted: int = 0
    country: str = ""
    member_since: str = ""


class JobDetail(BaseModel):
    job: JobPosting
    client: ClientSummary | None = None
    spec: JobSpec | None = None
    risk: RiskReport | None = None
    fit: FitReport | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    price: PriceQuote | None = None
    decision: BidDecision | None = None
    status: JobStatus = "new"
    sanitized_notes: list[str] = Field(
        default_factory=list,
        description="Untrusted-content handling notes, e.g. an instruction embedded in the post was ignored.",
    )
    latest_run_id: str | None = None
    approval_id: str | None = None


class AnalyzeResponse(BaseModel):
    run_id: str
    job_id: str
    status: Literal["queued", "running"] = "queued"


class SkipRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class SkipResponse(BaseModel):
    job_id: str
    status: JobStatus = "skipped"
