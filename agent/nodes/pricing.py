"""Pricing Strategist: bid from market statistics, client budget and the user's floor (+ Connects ROI)."""
from __future__ import annotations

from agent.handoffs import PriceQuote
from agent.nodes.common import Ctx
from agent.prompts import load_prompt


async def pricing(state: dict, ctx: Ctx) -> dict:
    job, spec = state["job"], state.get("job_spec", {})
    st = state.get("settings", {}) or {}
    cat = spec.get("category") or job.get("category", "general")
    stats = await ctx.call("pricing", "get_market_stats", {"category": cat, "skills": job.get("required_skills", [])})
    stats = stats.get("stats", stats) if isinstance(stats, dict) else {}
    balance = await ctx.call("pricing", "get_connects_balance", {})
    b = job.get("budget") or {}
    hourly = b.get("type") == "hourly"
    p25, p50, p75 = (float(stats.get(k) or 0) for k in ("p25", "p50", "p75"))
    if hourly:
        p25 = p25 or float(stats.get("hourly_p50", 30)) * 0.8
        p50 = float(stats.get("hourly_p50") or p50 or 30)
        p75 = p75 or p50 * 1.25
    p25, p75 = p25 or p50 * 0.8, p75 or p50 * 1.25
    rate = float(st.get("hourly_rate_usd", 0))
    floor = rate if hourly else float(st.get("min_project_budget_usd", 0))
    fit = float(state.get("fit_report", {}).get("score", 0.5))
    pc = ctx.cfg.get("pricing", {})
    ceiling = float(b.get("max") or 0)
    if hourly:
        # an hourly bid is the user's own rate, kept inside what the client says they will pay
        target = rate or p50
        if b.get("min") and target < float(b["min"]):
            target = float(b["min"])
    else:
        days = float(spec.get("timeline_days") or job.get("duration_days") or 0)
        cost_basis = rate * days * float(pc.get("billable_hours_per_day", 4)) if rate and days else 0.0
        budget_mid = (float(b.get("min") or 0) + ceiling) / 2 if ceiling else 0.0
        w = float(pc.get("cost_basis_weight", 0.6))
        parts = [(w, cost_basis), (1 - w, budget_mid)]
        have = [(wt, v) for wt, v in parts if v > 0]
        if have:
            target = sum(wt * v for wt, v in have) / sum(wt for wt, _ in have)
        else:
            target = p25 + (p75 - p25) * (0.35 + 0.4 * fit)   # no cost basis and no budget: use the market
        target = min(max(target, p25 * 0.5), max(p75, target))  # keep it near the observed market range
    amount = max(target, floor)
    if ceiling and amount > ceiling:
        amount = ceiling
    if amount < floor:
        amount = floor
    amount = round(amount, 2 if hourly else 0)
    policy_cost = ctx.policy.connects_cost(ctx.cfg["policy"]["connects_per_proposal_default"])
    connects = int(job.get("connects_cost") or policy_cost)
    remaining = int(balance.get("balance", 0)) if isinstance(balance, dict) else 0
    expected_value = fit * (1 - float(state.get("risk_report", {}).get("score", 0))) * max(amount, 1)
    worth = connects <= remaining and expected_value > connects * 0.5
    rationale = (f"market p25/p50/p75 = {p25:.0f}/{p50:.0f}/{p75:.0f} for '{cat}' (n={stats.get('n', '?')}); "
                 f"fit {fit:.2f} -> {amount:.0f}; floor {floor:.0f}; client ceiling {ceiling or 'unknown'}; "
                 f"Connects {connects} of {remaining} left ({'worth it' if worth else 'not worth it'}).")
    quote = PriceQuote(amount=amount, band_low=round(p25, 2), band_high=round(p75, 2), connects_cost=connects,
                       worth_connects=worth, rationale=rationale)
    if ctx.use_llm("pricing"):
        _, system = load_prompt("pricing")
        res = await ctx.llm.chat("pricing", system, rationale, max_tokens=160)
        if res.text:
            quote.rationale = rationale + " " + res.text[:240]
    return {"price_quote": quote.model_dump()}
