"""Structured hand-offs between agents (C3).

Every object a later graph step *decides on* is one of these Pydantic models, never free text.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Decision = Literal["skip", "watch", "bid"]
ClaimLabel = Literal["supported", "partly_supported", "unsupported"]
Outcome = Literal["won", "replied", "ignored"]


class Budget(BaseModel):
    type: Literal["fixed", "hourly"] = "fixed"
    min: float | None = None
    max: float | None = None
    currency: str = "USD"


class JobSpec(BaseModel):
    """Job Analyst output: what the client actually wants."""

    job_id: str
    title: str
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list, description="atomic requirements, one retrieval each")
    budget: Budget = Field(default_factory=Budget)
    budget_min: float | None = None
    budget_max: float | None = None
    timeline_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list)
    category: str = "general"


class RiskReport(BaseModel):
    """Risk Assessor output: client quality and scam / policy signals."""

    score: float = Field(ge=0, le=1, description="0 = safe, 1 = very risky")
    client_quality: float = Field(ge=0, le=1, default=0.5)
    flags: list[str] = Field(default_factory=list)
    is_scam: bool = False
    injection_detected: bool = False
    explanation: str = ""


class EvidenceRef(BaseModel):
    """One piece of portfolio evidence (shape returned by the Portfolio MCP server)."""

    id: str
    project_id: str | None = None
    type: str  # cv | case_study | readme | code | review | proposal
    source: str = ""
    title: str = ""
    text: str = ""
    date: str | None = None
    outcome: Outcome | None = None
    skills: list[str] = Field(default_factory=list)
    score: float = 0.0


class RequirementMatch(BaseModel):
    requirement: str
    evidence_ids: list[str] = Field(default_factory=list)
    strength: float = Field(ge=0, le=1, default=0.0)


class FitReport(BaseModel):
    """Fit Matcher output: requirement -> evidence matrix and an overall score."""

    score: float = Field(ge=0, le=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    matrix: list[RequirementMatch] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class BidDecision(BaseModel):
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    auto_skipped: bool = False


class PriceQuote(BaseModel):
    amount: float
    currency: str = "USD"
    band_low: float
    band_high: float
    connects_cost: int = 0
    worth_connects: bool = True
    rationale: str = ""


class Claim(BaseModel):
    text: str
    label: ClaimLabel = "unsupported"
    evidence_ids: list[str] = Field(default_factory=list)
    rewritten: str | None = None
    removed: bool = False


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    revision: int = 0
    status: str = "pending_review"


class Critique(BaseModel):
    ok: bool
    score: float = Field(ge=0, le=1, default=0.0)
    issues: list[str] = Field(default_factory=list)
    send_back: bool = False


class ComplianceVerdict(BaseModel):
    ok: bool
    blocked: bool = False
    violations: list[str] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)
    cleaned_text: str | None = None


class DryRunPreview(BaseModel):
    payload: dict
    connects_cost: int = 0
    balance_after: int | None = None


class ApprovalRequest(BaseModel):
    """Payload attached to every LangGraph interrupt() (C5)."""

    kind: Literal["proposal", "message", "connects"]
    thread_id: str
    job_id: str | None = None
    draft: ProposalDraft | dict
    evidence: list[EvidenceRef] = Field(default_factory=list)
    risk: RiskReport | None = None
    price: PriceQuote | None = None
    dry_run: DryRunPreview | None = None
    critic: Critique | None = None
    compliance: ComplianceVerdict | None = None


class ApprovalDecision(BaseModel):
    """Resume value for interrupt()."""

    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = None
    edited_answers: list[str] | None = None
    reason: str | None = None


class IntentResult(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "other"]
    confidence: float = Field(ge=0, le=1, default=0.5)
    injection_detected: bool = False
