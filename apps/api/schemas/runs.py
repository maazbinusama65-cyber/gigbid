"""Agent run, streaming event and trace models."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

RunStatus = Literal[
    "running",
    "awaiting_approval",
    "submitted",
    "skipped",
    "rejected",
    "blocked",
    "needs_attention",
    "dead_letter",
]
EventType = Literal["node_start", "node_end", "interrupt", "token", "done", "error", "degraded"]


class RunEvent(BaseModel):
    """One SSE payload on /api/runs/{id}/stream."""

    type: EventType
    node: str | None = None
    ts: str
    data: dict[str, Any] = Field(default_factory=dict)


class RunStep(BaseModel):
    node: str
    label: str = ""
    status: Literal["pending", "running", "done", "interrupted", "failed", "skipped"] = "pending"
    started_at: str | None = None
    duration_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    summary: str = ""
    model: str | None = None


class RunSummary(BaseModel):
    run_id: str
    kind: Literal["bid", "conversation", "scout"] = "bid"
    job_id: str | None = None
    title: str = ""
    status: RunStatus
    started_at: str
    finished_at: str | None = None
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    trace_id: str = ""


class RunList(BaseModel):
    runs: list[RunSummary]


class RunDetail(BaseModel):
    summary: RunSummary
    steps: list[RunStep]
    trace_url: str = ""
    approval_id: str | None = None
    notes: list[str] = Field(default_factory=list)


class TraceSpan(BaseModel):
    span_id: str
    parent_id: str | None = None
    name: str
    kind: Literal["graph", "node", "llm", "tool", "mcp"] = "node"
    start_ms: int = 0
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceResponse(BaseModel):
    trace_id: str
    run_id: str
    url: str = ""
    spans: list[TraceSpan]
    total_cost_usd: float = 0.0
    total_ms: int = 0
