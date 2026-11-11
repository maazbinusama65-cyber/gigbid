"""Input constraints and declared output models for the Marketplace MCP server."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ----------------------------------------------------------------- reusable input types
IdempotencyKey = Annotated[
    str,
    Field(
        min_length=8, max_length=200, pattern=r"^[!-~]+$",
        description="REQUIRED. Unique id for this logical write, e.g. a UUID or "
                    "'<run_id>:<job_id>:submit'. Re-sending the same key never repeats the write "
                    "or spends Connects twice; it returns the first result.",
    ),
]
DryRun = Annotated[
    bool,
    Field(description="If true nothing is created, sent or spent: returns exactly the payload "
                      "that would be sent and what it would cost."),
]
TraceId = Annotated[
    str | None,
    Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$",
          description="Optional trace id, copied to the audit log."),
]
JobId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$",
                              description="Marketplace job id, e.g. from search_jobs.")]
ProposalId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$",
                                   description="Id of a proposal draft created by "
                                               "create_proposal_draft.")]
ThreadId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$",
                                 description="Conversation thread id from list_messages.")]
ClientId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:\-]+$",
                                 description="Client id from a job (client_id).")]


class _Open(BaseModel):
    """Upstream-owned shape: declared fields are guaranteed, extras pass through."""

    model_config = ConfigDict(extra="allow")


# ----------------------------------------------------------------- read outputs
class JobBudget(_Open):
    type: str = "fixed"
    min: float | None = None
    max: float | None = None
    currency: str = "USD"


class Job(_Open):
    job_id: str
    client_id: str | None = None
    title: str = ""
    description: str = ""
    category: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    budget: JobBudget | None = None
    duration_days: int | None = None
    screening_questions: list[str] = Field(default_factory=list)
    posted_at: str | None = None
    connects_cost: int | None = None


class JobSearchResult(BaseModel):
    jobs: list[Job]
    next_cursor: str | None = None


class ClientHistory(_Open):
    client_id: str
    name: str | None = None
    industry: str | None = None
    payment_verified: bool | None = None
    total_spent: float | None = None
    hire_rate: float | None = None
    avg_rating: float | None = None
    jobs_posted: int | None = None
    member_since: str | None = None
    country: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class ConnectsBalance(_Open):
    balance: int
    weekly_allowance: int | None = None
    spent_this_week: int | None = None


class MessageList(BaseModel):
    thread_id: str | None = Field(default=None, description="Echo of the requested thread.")
    threads: list[dict[str, Any]] = Field(
        default_factory=list, description="Filled when no thread_id was given.")
    messages: list[dict[str, Any]] = Field(
        default_factory=list, description="Filled when thread_id was given.")


class MarketEvent(_Open):
    event_id: str | int
    ts: str | None = None
    type: str
    proposal_id: str | None = None
    thread_id: str | None = None


class EventList(BaseModel):
    events: list[MarketEvent]
    last_event_id: str | int | None = Field(
        default=None, description="Pass as `since` next time to get only newer events.")


class MarketStats(_Open):
    category: str | None = None
    n: int | None = Field(default=None, description="Number of comparable past jobs.")
    p10: float | None = None
    p25: float | None = None
    p50: float | None = Field(default=None, description="Median final price (USD).")
    p75: float | None = None
    p90: float | None = None
    hourly_p50: float | None = None
    skills: list[dict[str, Any]] | None = Field(
        default=None, description="Per-skill breakdown (skill, n, percentiles) when available.")


class PolicyRule(_Open):
    id: str | None = None
    type: str | None = None
    pattern: str | None = None
    value: Any = None
    description: str = ""


class PlatformPolicy(_Open):
    version: str | int | None = None
    connects_per_proposal: int | None = None
    rules: list[PolicyRule] = Field(default_factory=list)
    rate_limit_rpm: int | None = None


# ----------------------------------------------------------------- write outputs
class ProposalWriteResult(BaseModel):
    proposal_id: str | None = Field(description="Null for dry runs (nothing was created).")
    status: Literal["preview", "draft", "submitted"]
    connects_cost: int = Field(description="Connects this action costs (or would cost).")
    balance_after: int | None = None
    connects_spent: int | None = Field(
        default=None, description="Connects actually spent (submitted proposals only).")
    balance: int | None = Field(default=None, description="Balance after the action (alias of balance_after).")
    payload: dict[str, Any] = Field(description="Exactly what was (or would be) sent.")
    dry_run: bool
    idempotent_replay: bool = Field(
        default=False, description="True when this is the stored result of an earlier identical call.")
    requires_user_confirmation: bool = Field(
        default=False, description="Live marketplace: the user must still confirm on the platform.")
    note: str | None = None


class MessageWriteResult(BaseModel):
    message_id: str | None = None
    thread_id: str
    status: Literal["preview", "draft", "sent"]
    payload: dict[str, Any]
    dry_run: bool
    idempotent_replay: bool = False
    requires_user_confirmation: bool = False
    note: str | None = None
