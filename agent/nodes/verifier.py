"""Claim verification node (R5, B3): split the draft into claims, check each against evidence,
remove or rewrite unsupported claims BEFORE the Critic sees the draft. Reports the unsupported-claim
rate before and after.
"""
from __future__ import annotations

from agent.handoffs import Claim, ProposalDraft
from agent.nodes.common import Ctx


def _rate(claims: list[dict]) -> tuple[int, int]:
    total = len(claims)
    return sum(1 for c in claims if c.get("label") == "unsupported"), total


async def verifier(state: dict, ctx: Ctx) -> dict:
    from rag.verify import verify_and_repair  # local import: heavy deps load lazily

    draft = ProposalDraft(**state["proposal_draft"])
    evidence = state.get("evidence", [])
    judge = None
    if ctx.use_llm("verifier"):
        judge = _make_llm_judge(ctx)
    pieces = [draft.cover_letter] + list(draft.screening_answers)
    new_pieces: list[str] = []
    all_claims: list[dict] = []
    before_unsup = before_total = after_unsup = after_total = 0
    for p in pieces:
        repaired, records = verify_and_repair(p, evidence, judge=judge) if judge else verify_and_repair(p, evidence)
        new_pieces.append(repaired)
        for r in records:
            all_claims.append(r if isinstance(r, dict) else r.model_dump())
        u, t = _rate([c for c in all_claims[-len(records):]] if records else [])
        before_unsup += u
        before_total += t
        after_total += sum(1 for c in (all_claims[-len(records):] if records else []) if not c.get("removed"))
    # claims that survive (not removed) and are still unsupported after repair
    survivors = [c for c in all_claims if not c.get("removed") and c.get("label") == "unsupported" and not c.get("rewritten")]
    after_unsup = len(survivors)
    draft.cover_letter = new_pieces[0]
    draft.screening_answers = new_pieces[1:]
    draft.claims = [Claim(**{k: v for k, v in c.items() if k in Claim.model_fields}) for c in all_claims]
    stats = {"claims": len(all_claims), "unsupported_before": before_unsup, "unsupported_after": after_unsup,
             "rate_before": round(before_unsup / max(1, before_total), 4),
             "rate_after": round(after_unsup / max(1, after_total or before_total), 4)}
    return {"proposal_draft": draft.model_dump(), "claim_stats": stats}


def _make_llm_judge(ctx: Ctx):
    """Optional LLM judge callable for rag.verify (sync wrapper not used: verify takes an async-free hook)."""
    return None  # deterministic verification is the default; an LLM judge is evaluated in evals/ablation
