"""Compliance Guard: enforce the policy pack (data-driven), strip contact details / guarantees /
injected payloads, and block with a visible reason when a draft cannot be made compliant."""
from __future__ import annotations

import re

from agent.guardrails import detect_injection
from agent.handoffs import ComplianceVerdict, ProposalDraft
from agent.nodes.common import Ctx

_CANARY = re.compile(r"[\"'“]([^\"'”]{3,40})[\"'”]|\b([A-Z]{3,}[A-Z0-9]*-\d+)\b")


def injected_tokens(job: dict) -> list[str]:
    """Strings an attacker asked the model to emit (quoted phrases and CANARY-123 style tokens)."""
    text = f"{job.get('title','')} {job.get('description','')}"
    toks: list[str] = []
    # look at the sentences that contain an injection and pull quoted / canary tokens out of them
    for sent in re.split(r"(?<=[.!?])\s+|\n", text):
        if detect_injection(sent):
            for a, b in _CANARY.findall(sent):
                tok = (a or b).strip()
                if tok:
                    toks.append(tok)
    return list(dict.fromkeys(toks))


async def compliance(state: dict, ctx: Ctx) -> dict:
    draft = ProposalDraft(**state["proposal_draft"])
    policy = ctx.policy
    try:  # platform-published rules (change-request hook): merged over the local pack
        remote = await ctx.call("compliance", "get_platform_policy", {})
        policy = type(policy).from_marketplace(remote)
    except Exception:  # degraded: fall back to local pack; never silently skip checks
        policy = ctx.policy
    texts = [draft.cover_letter] + list(draft.screening_answers)
    violations: list[str] = []
    redactions: list[str] = []
    cleaned: list[str] = []
    bad_tokens = injected_tokens(state.get("job", {}))
    for t in texts:
        for tok in bad_tokens:
            if tok.lower() in t.lower():
                violations.append(f"injected_instruction_followed: '{tok}'")
                t = re.sub(re.escape(tok), "", t, flags=re.I)
        c, red = policy.clean(t)
        redactions += red
        cleaned.append(c)
    blocking = [v for v in policy.check(cleaned[0]) if v.action == "block"]
    for v in blocking:
        violations.append(f"{v.rule_id}: {v.description} ({v.snippet})")
    unsupported = state.get("claim_stats", {}).get("unsupported_after", 0)
    if unsupported:
        violations.append(f"{unsupported} unsupported claim(s) would be sent (fabricated experience)")
    blocked = bool(blocking) or bool(unsupported)
    verdict = ComplianceVerdict(ok=not blocked, blocked=blocked, violations=violations, redactions=redactions,
                                cleaned_text=cleaned[0])
    out: dict = {"compliance_verdict": verdict.model_dump()}
    if blocked:
        out["status"] = "blocked"
        out["status_reason"] = "; ".join(violations)[:300]
    else:
        draft.cover_letter, draft.screening_answers = cleaned[0], cleaned[1:]
        out["proposal_draft"] = draft.model_dump()
    return out
