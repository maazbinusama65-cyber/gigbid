"""Proposal studio models."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agent.handoffs import (
    ComplianceVerdict,
    Critique,
    DryRunPreview,
    EvidenceRef,
    PriceQuote,
    ProposalDraft,
    RiskReport,
)


class ProposalStudio(BaseModel):
    job_id: str
    job_title: str
    draft: ProposalDraft
    paragraphs: list[str] = Field(description="cover_letter split on blank lines")
    screening_questions: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    critic: Critique | None = None
    compliance: ComplianceVerdict | None = None
    risk: RiskReport | None = None
    price: PriceQuote | None = None
    dry_run: DryRunPreview | None = None
    approval_id: str | None = Field(default=None, description="pending approval for this draft, if any")
    approval_status: str | None = None
    marketplace_degraded: bool = False


class RegenerateRequest(BaseModel):
    paragraph_index: int = Field(ge=0)
    instruction: str = Field(default="", max_length=500)
