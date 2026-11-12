"""Fit Matcher: map every requirement to portfolio evidence (through the Portfolio MCP tool).

Runs in parallel with the Job Analyst, so it extracts requirements itself (shared helper).
Requirement decomposition (retrieval variant V1) happens here; the per-requirement retrieval
variant (V2/V3/...) is whatever the Portfolio server is configured to serve.
"""
from __future__ import annotations

import asyncio
import re

from agent.handoffs import EvidenceRef, FitReport, RequirementMatch
from agent.nodes.analyst import extract_requirements
from agent.nodes.common import Ctx
from agent.prompts import load_prompt


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9+#]+", " ", s.lower()).strip()


def requirement_strength(req: str, items: list[dict]) -> tuple[float, list[str]]:
    """Strength 0..1 that the evidence proves the requirement.

    Evidence `skills` metadata counts (implied skills live there), then literal mention in text.
    Rank discounts: the top hit counts most. A semantically-retrieved item with no lexical or
    metadata support is capped at 0.3 so retrieval noise cannot fake a fit.
    """
    r = _norm(req)
    toks = [t for t in r.split() if len(t) > 2]
    best, ids = 0.0, []
    for rank, it in enumerate(items):
        skills = {_norm(s) for s in it.get("skills", [])}
        text = _norm(it.get("title", "") + " " + it.get("text", ""))
        if r in skills:
            s = 1.0
        elif r and f" {r} " in f" {text} ":
            s = 0.9
        elif toks and sum(t in text.split() for t in toks) / len(toks) >= 0.6:
            s = 0.7
        else:
            s = 0.3 if rank == 0 else 0.0
        s *= 1.0 if rank == 0 else 0.9 if rank == 1 else 0.8
        if s > 0.3:
            ids.append(it["id"])
        best = max(best, s)
    return round(best, 3), ids


async def fit_matcher(state: dict, ctx: Ctx) -> dict:
    job = state["job"]
    reqs = extract_requirements(job) or [job.get("title", "")]
    k = int(ctx.cfg["rag"].get("k", 5))
    pids = (state.get("settings") or {}).get("portfolio_ids") or [state.get("persona_id")]

    async def search(r: str) -> dict:
        """One search per requirement and portfolio (the persona's corpus plus the user's own uploads)."""
        outs = await asyncio.gather(*[
            ctx.call("fit_matcher", "search_evidence", {"requirement": r, "k": k, **({"portfolio_id": p} if p else {})})
            for p in pids])
        merged: dict[str, dict] = {}
        for res in outs:
            for it in (res.get("items", res) if isinstance(res, dict) else res):
                if it["id"] not in merged or it.get("score", 0) > merged[it["id"]].get("score", 0):
                    merged[it["id"]] = it
        return {"items": sorted(merged.values(), key=lambda x: -x.get("score", 0))[:k]}

    results = await asyncio.gather(*[search(r) for r in reqs])
    matrix: list[RequirementMatch] = []
    evidence: dict[str, dict] = {}
    for r, res in zip(reqs, results, strict=True):
        items = res.get("items", res) if isinstance(res, dict) else res
        for it in items:
            evidence[it["id"]] = EvidenceRef(**{kk: it.get(kk) for kk in EvidenceRef.model_fields if kk in it}).model_dump()
        s, ids = requirement_strength(r, items)
        matrix.append(RequirementMatch(requirement=r, evidence_ids=ids[:3], strength=s))
    mean = sum(m.strength for m in matrix) / max(1, len(matrix))
    # outcome-aware nudge: evidence from won/replied proposals is a (small) positive signal
    ev_by_id = evidence
    won = sum(1 for m in matrix for i in m.evidence_ids if ev_by_id.get(i, {}).get("outcome") in ("won", "replied"))
    score = min(1.0, mean + 0.02 * min(won, 3))
    matched = [m.requirement for m in matrix if m.strength >= 0.6]
    missing = [m.requirement for m in matrix if m.strength < 0.4]
    reasons = [f"{len(matched)}/{len(matrix)} requirements backed by portfolio evidence"]
    if missing:
        reasons.append("no evidence for: " + ", ".join(missing[:4]))
    report = FitReport(score=round(score, 3), matched_skills=matched, missing_skills=missing, matrix=matrix,
                       evidence_ids=sorted({i for m in matrix for i in m.evidence_ids}), reasons=reasons)
    if ctx.use_llm("fit_matcher") and matrix:
        _, system = load_prompt("fit_matcher")
        payload = "\n".join(f"- {m.requirement}: " + " | ".join(f"[{i}] {ev_by_id[i]['text'][:160]}" for i in m.evidence_ids if i in ev_by_id)
                            for m in matrix)
        res = await ctx.llm.chat("fit_matcher", system, payload, max_tokens=500)
        if res.text:
            report.reasons.append("llm review: " + res.text[:200])
    return {"fit_report": report.model_dump(), "evidence": list(evidence.values())}
