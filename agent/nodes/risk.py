"""Risk Assessor: client quality from history + scam / free-work / off-platform / injection flags."""
from __future__ import annotations

from agent.guardrails import detect_injection, wrap_untrusted
from agent.handoffs import RiskReport
from agent.nodes.common import Ctx
from agent.nodes.scout import unwrap
from agent.prompts import load_prompt

HARD_SCAM_FLAGS = {"unpaid_trial", "off_platform_contact", "payment_upfront", "credential_phishing",
                   "guarantee_demand"}


def client_quality(c: dict) -> float:
    """0..1 from public client history. Unknown clients are neutral (0.5), not zero."""
    if not c:
        return 0.5
    q = 0.0
    q += 0.25 if c.get("payment_verified") else 0.0
    q += 0.25 * min(1.0, float(c.get("hire_rate", 0.0) or 0.0))
    q += 0.25 * min(1.0, float(c.get("avg_rating", 0.0) or 0.0) / 5.0)
    q += 0.25 * min(1.0, float(c.get("total_spent", 0.0) or 0.0) / 10000.0)
    return round(q, 3)


async def risk_assessor(state: dict, ctx: Ctx) -> dict:
    job = state["job"]
    text = f"{job.get('title','')}\n{job.get('description','')}\n" + "\n".join(job.get("screening_questions", []))
    flags = dict(ctx.policy.scam_flags(text))
    injections = detect_injection(text)
    client: dict = {}
    if job.get("client_id"):
        client = unwrap(await ctx.call("risk_assessor", "get_client_history", {"client_id": job["client_id"]}), "client")
    cq = client_quality(client)
    b = job.get("budget") or {}
    if b.get("max") in (0, 0.0) and b.get("type", "fixed") == "fixed":
        flags.setdefault("zero_budget", "budget is 0")
    if client and not client.get("payment_verified"):
        flags.setdefault("payment_unverified", "payment not verified")
    is_scam = bool(HARD_SCAM_FLAGS & set(flags)) or "zero_budget" in flags
    score = 0.9 if is_scam else min(0.69, 0.55 * (1 - cq) + 0.12 * len(flags))
    if injections:
        flags["injection_detected"] = injections[0]
        score = min(1.0, max(score, 0.35) + 0.2)
    explanation = ("; ".join(f"{k}: '{v}'" for k, v in flags.items()) or "no risk signals") + f" | client_quality={cq}"
    report = RiskReport(score=round(score, 3), client_quality=cq, flags=sorted(flags), is_scam=is_scam,
                        injection_detected=bool(injections), explanation=explanation)
    if ctx.use_llm("risk_assessor") and not is_scam and (flags or cq < 0.35):
        _, system = load_prompt("risk_assessor")
        res = await ctx.llm.chat("risk_assessor", system,
                                 wrap_untrusted(text[:1800]) + f"\nclient={client}\nrule_flags={sorted(flags)}",
                                 schema=RiskReport, max_tokens=300)
        if res.parsed is not None and res.parsed.is_scam and not injections:
            report.is_scam = True
            report.score = max(report.score, 0.85)
            report.flags = sorted(set(report.flags) | set(res.parsed.flags))
            report.explanation += f" | llm: {res.parsed.explanation[:160]}"
    return {"risk_report": report.model_dump()}
