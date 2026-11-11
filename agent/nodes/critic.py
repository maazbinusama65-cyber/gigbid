"""Critic: grounding, personalisation, opening, length. Sends back at most `max_revisions` times."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent.handoffs import Critique
from agent.nodes.common import Ctx, words
from agent.prompts import load_prompt

GENERIC_OPENERS = re.compile(
    r"^(dear (sir|madam|hiring|client)|hello(,)? (sir|there)|hi there|i am writing to|i hope this|greetings|"
    r"i am (very )?(excited|interested|passionate)|i came across your|with (over )?\d+ years)", re.I)


class _LLMCritique(BaseModel):
    ok: bool
    score: float = Field(ge=0, le=1, default=0.5)
    issues: list[str] = Field(default_factory=list)
    send_back: bool = False


async def critic(state: dict, ctx: Ctx) -> dict:
    th = ctx.cfg["thresholds"]
    draft = state["proposal_draft"]
    text = draft["cover_letter"]
    job = state["job"]
    n = len(words(text))
    issues: list[str] = []
    if GENERIC_OPENERS.search(text.strip()):
        issues.append("generic opening: start with the client's specific problem")
    if n > th["max_proposal_words"]:
        issues.append(f"too long ({n} words > {th['max_proposal_words']})")
    if n < th["min_proposal_words"]:
        issues.append(f"too short ({n} words < {th['min_proposal_words']}): add specific evidence")
    kw = {w.lower() for s in job.get("required_skills", []) for w in re.findall(r"[A-Za-z0-9+#]+", s)} | \
         {w.lower() for w in re.findall(r"[A-Za-z]{5,}", job.get("title", ""))}
    if kw and not any(k in text.lower() for k in kw):
        issues.append("not personalised: mention the client's tools or problem by name")
    stats = state.get("claim_stats", {})
    if stats.get("unsupported_after", 0) > 0:
        issues.append(f"{stats['unsupported_after']} unsupported claim(s) remain")
    if not draft.get("evidence_ids"):
        issues.append("no evidence cited")
    score = max(0.0, 1.0 - 0.2 * len(issues))
    if ctx.use_llm("critic"):
        _, system = load_prompt("critic")
        res = await ctx.llm.chat("critic", system, f"JOB: {job.get('title')} | SKILLS: {job.get('required_skills')}\n\nDRAFT:\n{text}",
                                 schema=_LLMCritique, max_tokens=300)
        if res.parsed is not None:
            issues += [i for i in res.parsed.issues if i not in issues][:3]
            score = min(score, res.parsed.score) if res.parsed.score else score
    revision = int(state.get("revision", 0))
    can_retry = revision < int(ctx.cfg["budgets"]["max_revisions"])
    ok = not issues
    c = Critique(ok=ok, score=round(score, 3), issues=issues, send_back=(not ok) and can_retry)
    return {"critiques": [c.model_dump()]}


def route_after_critic(state: dict) -> str:
    last = (state.get("critiques") or [{}])[-1]
    return "writer" if last.get("send_back") else "compliance"
