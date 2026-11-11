"""Pydantic models for the Portfolio MCP server (inputs with real constraints, declared outputs)."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

EvidenceType = Literal["cv", "case_study", "readme", "code", "review", "proposal"]
Outcome = Literal["won", "replied", "ignored"]

PortfolioIdParam = Annotated[
    str | None,
    Field(
        default=None,
        pattern=r"^[a-z0-9_\-]{1,40}$",
        description="Which portfolio to search. Omit to use the server's default portfolio.",
    ),
]


class EvidenceFilters(BaseModel):
    """Optional narrowing of a search. All fields optional; unknown keys are rejected."""

    model_config = {"extra": "forbid"}

    types: list[EvidenceType] | None = Field(
        default=None, max_length=6, description="Only these evidence types, e.g. ['case_study']."
    )
    project_id: str | None = Field(default=None, max_length=80, description="Only this project.")
    skills: list[str] | None = Field(
        default=None, max_length=10, description="Evidence must mention at least one of these skills."
    )
    outcome: Outcome | None = Field(
        default=None, description="For past proposals only: won, replied or ignored."
    )
    since: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}(-\d{2})?$", description="Only evidence dated on/after YYYY-MM[-DD]."
    )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class EvidenceItem(BaseModel):
    id: str = Field(description="Stable evidence id. Cite this in claims.")
    project_id: str | None = None
    type: str = Field(description="cv | case_study | readme | code | review | proposal")
    source: str = Field(default="", description="File or origin the text came from.")
    title: str = ""
    text: str = Field(default="", description="The evidence passage itself.")
    date: str | None = None
    outcome: str | None = Field(default=None, description="won | replied | ignored (past proposals)")
    skills: list[str] = Field(default_factory=list)
    score: float = 0.0


class SearchEvidenceResult(BaseModel):
    items: list[EvidenceItem]
    portfolio_id: str
    retriever: str = Field(description="Which retrieval backend answered (rag variant or local).")


class CaseStudy(BaseModel):
    id: str
    project_id: str
    title: str
    markdown: str = Field(description="Full case study text.")
    skills: list[str] = Field(default_factory=list)
    industry: str | None = None
    date: str | None = None
    outcome_summary: str | None = None
    reviews: list[dict[str, Any]] = Field(default_factory=list, description="Client reviews for it.")
    related_proposal_ids: list[str] = Field(default_factory=list)


class SkillCount(BaseModel):
    name: str
    count: int = Field(description="Number of projects that demonstrate the skill.")


class SkillList(BaseModel):
    skills: list[SkillCount]
    portfolio_id: str
