"""Typed graph state (C2).

Three things are kept apart (and the report says so):
  * STATE      - this file: what the job / conversation needs *right now*. Checkpointed.
  * TRACE      - agent/trace.py: every tool call, argument, result, observation. Append-only audit,
                 stored outside graph state (keyed by run/trace id) so state stays small.
  * MEMORY     - agent/memory/: only *promoted* knowledge, written to a LangGraph store by rule.
"""
from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

Status = str  # running | awaiting_approval | submitted | skipped | rejected | blocked | needs_attention | dead_letter


def merge_evidence(left: list[dict] | None, right: list[dict] | None) -> list[dict]:
    """Reducer for parallel branches: union by evidence id, keep the best score."""
    out: dict[str, dict] = {e["id"]: e for e in (left or [])}
    for e in right or []:
        cur = out.get(e["id"])
        if cur is None or e.get("score", 0) > cur.get("score", 0):
            out[e["id"]] = e
    return list(out.values())


def merge_dict(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


def last_wins(left: Any, right: Any) -> Any:
    return right if right is not None else left


class BidState(TypedDict, total=False):
    # identity / scope (tenant)
    thread_id: str
    run_id: str
    user_id: str
    persona_id: str
    # job + analyses (written by parallel branches: distinct keys, reducers where shared)
    job_id: str
    job: dict[str, Any]
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    evidence: Annotated[list[dict[str, Any]], merge_evidence]
    # decision / price
    decision: dict[str, Any]
    price_quote: dict[str, Any]
    # drafts / verification / critiques / compliance
    proposal_draft: dict[str, Any]
    claim_stats: dict[str, Any]          # unsupported-claim rate before / after verification
    critiques: Annotated[list[dict[str, Any]], operator.add]
    compliance_verdict: dict[str, Any]
    revision: int
    # approvals and outcomes
    approvals: Annotated[list[dict[str, Any]], operator.add]
    approval_status: str                  # pending | approved | edited | rejected
    dry_run: dict[str, Any]
    submission: dict[str, Any]
    outcome: dict[str, Any]
    # control
    status: Status
    status_reason: str
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    autonomy: dict[str, Any]
    settings: dict[str, Any]              # user floor, weekly connects budget, filters


class ConversationState(TypedDict, total=False):
    thread_id: str
    run_id: str
    user_id: str
    persona_id: str
    marketplace_thread_id: str
    job_id: str
    messages: list[dict[str, Any]]
    last_message: dict[str, Any]
    intent: dict[str, Any]
    reply_draft: dict[str, Any]
    slots: list[dict[str, Any]]
    compliance_verdict: dict[str, Any]
    approvals: Annotated[list[dict[str, Any]], operator.add]
    approval_status: str
    sent: dict[str, Any]
    pipeline_stage: str
    status: Status
    status_reason: str
    steps: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    errors: Annotated[list[str], operator.add]
    settings: dict[str, Any]
