"""Human-in-the-loop (R4, C5): dry-run preview, interrupt() approval, edit/reject handling, and the
exactly-once submit. The graph never auto-sends: `submit` refuses unless a human approved."""
from __future__ import annotations

import difflib
import hashlib

from langgraph.types import interrupt

from agent.handoffs import (ApprovalDecision, ApprovalRequest, ComplianceVerdict, Critique, DryRunPreview,
                            EvidenceRef, PriceQuote, ProposalDraft, RiskReport)
from agent.nodes.common import Ctx


def _key(state: dict, suffix: str) -> str:
    return f"{state['thread_id']}:{suffix}"


def _draft_hash(d: dict) -> str:
    return hashlib.sha1((d["cover_letter"] + "|".join(d.get("screening_answers", []))).encode()).hexdigest()[:10]


async def dry_run(state: dict, ctx: Ctx) -> dict:
    """Read-only preview of exactly what would be sent and what it costs (shown on the approval screen)."""
    d = state["proposal_draft"]
    price = state.get("price_quote", {})
    args = {"job_id": state["job_id"], "cover_letter": d["cover_letter"], "screening_answers": d["screening_answers"],
            "bid_amount": price.get("amount", 0), "dry_run": True,
            "idempotency_key": _key(state, f"dry:{_draft_hash(d)}")}
    res = await ctx.call("submitter", "create_proposal_draft", args)
    payload = res.get("payload", res) if isinstance(res, dict) else {}
    prev = DryRunPreview(payload=payload, connects_cost=int(res.get("connects_cost", price.get("connects_cost", 0))),
                         balance_after=res.get("balance_after"))
    ctx._trace("approval_requested", "dry_run", job_id=state["job_id"], connects=prev.connects_cost)
    return {"dry_run": prev.model_dump(), "status": "awaiting_approval"}


async def approval(state: dict, ctx: Ctx) -> dict:
    d = ProposalDraft(**state["proposal_draft"])
    ev = [EvidenceRef(**e) for e in state.get("evidence", []) if e["id"] in set(d.evidence_ids)]
    crit = (state.get("critiques") or [None])[-1]
    price = PriceQuote(**state["price_quote"]) if state.get("price_quote") else None
    settings = state.get("settings", {}) or {}
    over = False
    if price and settings.get("weekly_connects_budget") is not None:
        over = (settings.get("connects_spent_this_week", 0) + price.connects_cost) > settings["weekly_connects_budget"]
    req = ApprovalRequest(
        kind="connects" if over else "proposal", thread_id=state["thread_id"], job_id=state["job_id"], draft=d,
        evidence=ev, risk=RiskReport(**state["risk_report"]) if state.get("risk_report") else None, price=price,
        dry_run=DryRunPreview(**state["dry_run"]) if state.get("dry_run") else None,
        critic=Critique(**crit) if crit else None,
        compliance=ComplianceVerdict(**state["compliance_verdict"]) if state.get("compliance_verdict") else None)
    raw = interrupt(req.model_dump(mode="json"))        # <-- graph pauses here, durable across restarts
    dec = ApprovalDecision.model_validate(raw)
    record = {"action": dec.action, "reason": dec.reason, "kind": req.kind, "draft_hash": _draft_hash(d.model_dump())}
    if dec.action == "reject":
        return {"approval_status": "rejected", "approvals": [record], "status": "rejected",
                "status_reason": dec.reason or "rejected by user",
                "outcome": {"rejected": True, "reason": dec.reason}}
    if dec.action == "edit" and (dec.edited_text is not None or dec.edited_answers is not None):
        original = d.cover_letter
        edited = dec.edited_text if dec.edited_text is not None else original
        diff = "\n".join(difflib.unified_diff(original.splitlines(), edited.splitlines(), "draft", "edited", lineterm=""))
        promoted = ctx.memory.record_edit(state.get("user_id", "anon"), state["job_id"], original, edited)
        record |= {"diff": diff, "promoted_memory": [p["id"] for p in promoted]}
        d.cover_letter = edited
        if dec.edited_answers is not None:
            d.screening_answers = dec.edited_answers
        d.status = "edited"
        return {"approval_status": "edited", "approvals": [record], "proposal_draft": d.model_dump(), "status": "running"}
    return {"approval_status": "approved", "approvals": [record], "status": "running"}


def route_after_approval(state: dict) -> str:
    s = state.get("approval_status")
    if s == "rejected":
        return "end"
    if s == "edited":
        return "recheck"          # edits are re-checked by Compliance before anything is sent
    return "submit"


async def submit(state: dict, ctx: Ctx) -> dict:
    if state.get("approval_status") not in ("approved", "edited"):
        raise RuntimeError("refusing to submit without human approval")      # hard guard: never auto-send
    if state.get("submission"):                                              # graph-level exactly-once
        return {"status": "submitted"}
    d = state["proposal_draft"]
    price = state.get("price_quote", {})
    created = await ctx.call("submitter", "create_proposal_draft", {
        "job_id": state["job_id"], "cover_letter": d["cover_letter"], "screening_answers": d["screening_answers"],
        "bid_amount": price.get("amount", 0), "dry_run": False, "idempotency_key": _key(state, "draft")})
    pid = created.get("proposal_id")
    sub = await ctx.call("submitter", "submit_proposal", {"proposal_id": pid, "idempotency_key": _key(state, "submit")})
    ctx._trace("submitted", "submit", proposal_id=pid, connects_spent=sub.get("connects_spent"))
    return {"submission": {"proposal_id": pid, **{k: sub.get(k) for k in ("status", "connects_spent", "balance")}},
            "status": "submitted"}
