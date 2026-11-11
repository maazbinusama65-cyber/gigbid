"""Decision node (join after the three parallel branches): skip / watch / bid. Pure rules from config."""
from __future__ import annotations

from agent.handoffs import BidDecision
from agent.nodes.common import Ctx


async def decide(state: dict, ctx: Ctx) -> dict:
    th = ctx.cfg["thresholds"]
    fit = state.get("fit_report", {})
    risk = state.get("risk_report", {})
    job = state.get("job", {})
    st = state.get("settings", {}) or {}
    autonomy = {**ctx.cfg.get("autonomy", {}), **(state.get("autonomy") or {})}
    reasons: list[str] = []
    fit_score, risk_score = float(fit.get("score", 0)), float(risk.get("score", 1))
    decision = "bid"
    if risk.get("is_scam"):
        decision = "skip"
        reasons.append("scam / policy risk: " + ", ".join(risk.get("flags", [])))
    elif risk_score > th["maximum_risk_score"]:
        decision = "skip"
        reasons.append(f"risk {risk_score:.2f} above {th['maximum_risk_score']}")
    elif fit_score < th["watch_fit_score"]:
        decision = "skip"
        reasons.append(f"fit {fit_score:.2f} below watch threshold {th['watch_fit_score']}")
    elif fit_score < th["minimum_fit_score"]:
        decision = "watch"
        reasons.append(f"fit {fit_score:.2f} between {th['watch_fit_score']} and {th['minimum_fit_score']}")
    budget_max = (job.get("budget") or {}).get("max")
    floor = st.get("min_project_budget_usd")
    if decision == "bid" and floor and budget_max and (job.get("budget") or {}).get("type") == "fixed" and budget_max < floor:
        decision = "skip"
        reasons.append(f"client budget {budget_max} below your minimum project budget {floor}")
    if decision == "bid":
        reasons.append(f"fit {fit_score:.2f}, risk {risk_score:.2f}")
    if st.get("force_bid") and decision in ("skip", "watch") and not risk.get("is_scam"):
        decision = "bid"
        reasons.append("user override: bid anyway")
    auto = bool(autonomy.get("auto_skip_low_fit")) and fit_score < th["auto_skip_fit_score"] and decision == "skip"
    d = BidDecision(decision=decision, reasons=reasons, auto_skipped=auto)
    out: dict = {"decision": d.model_dump()}
    if decision != "bid":
        out["status"] = "skipped"
        out["status_reason"] = "; ".join(reasons)
    return out
