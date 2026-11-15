"""Decision node (join after the three parallel branches): skip / watch / bid. Pure rules from config."""
from __future__ import annotations

from agent.handoffs import BidDecision
from agent.nodes.common import HALT, Ctx


async def decide(state: dict, ctx: Ctx) -> dict:
    if state.get("status") in HALT:
        # An upstream branch dead-lettered or needs attention. Deciding on its missing output would turn a crash
        # into a "skip" and hide it from the metrics, so the failure status is left untouched.
        return {}
    th = ctx.cfg["thresholds"]
    fit = state.get("fit_report", {})
    risk = state.get("risk_report", {})
    job = state.get("job", {})
    st = state.get("settings", {}) or {}
    autonomy = {**ctx.cfg.get("autonomy", {}), **(state.get("autonomy") or {})}
    reasons: list[str] = []
    fit_score, risk_score = float(fit.get("score", 0)), float(risk.get("score", 1))
    min_fit = float(st.get("min_fit_score", th["minimum_fit_score"]))     # user setting overrides the default
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
    elif fit_score < min_fit:
        decision = "watch"
        reasons.append(f"fit {fit_score:.2f} between {th['watch_fit_score']} and {th['minimum_fit_score']}")
    budget_max = (job.get("budget") or {}).get("max")
    floor = st.get("min_project_budget_usd")
    if decision == "bid" and floor and budget_max and (job.get("budget") or {}).get("type") == "fixed" and budget_max < floor:
        decision = "skip"
        reasons.append(f"client budget {budget_max} below your minimum project budget {floor}")
    rate = st.get("hourly_rate_usd")
    ratio_floor = float(th.get("min_hourly_rate_ratio", 0.8))
    if (decision == "bid" and rate and budget_max and (job.get("budget") or {}).get("type") == "hourly"
            and budget_max < ratio_floor * float(rate)):
        decision = "skip"
        reasons.append(f"client's top hourly rate {budget_max} is below {ratio_floor:.0%} of your rate {rate}")
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
