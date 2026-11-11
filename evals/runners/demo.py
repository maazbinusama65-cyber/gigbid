"""One job end to end against GigSim through the MCP servers: `python -m evals.runners.demo [persona] [job_id]`."""
from __future__ import annotations

import asyncio
import json
import sys

from evals.harness import eval_env, load_profile, run_job
from evals.runners.common import dev_jobs


async def main(persona: str = "ai_ml", job_id: str | None = None, profile: str = "stub") -> None:
    gold = dev_jobs(persona)
    pick = next((g for g in gold if g["label"] == "bid" and not g["is_scam"] and not g["has_injection"]), gold[0])
    job_id = job_id or pick["job_id"]
    prof = load_profile(persona)
    settings = {"min_project_budget_usd": prof["min_project_budget_usd"], "hourly_rate_usd": prof["hourly_rate_usd"]}
    async with eval_env(profile, persona) as env:
        last = await run_job(env, persona, job_id, settings)
        st = last.get("state", {})
        print("job:", job_id, "| gold:", next(g for g in gold if g["job_id"] == job_id)["label"])
        print("status:", st.get("status"), "| interrupted:", last.get("interrupted"), "| latency_s:", round(last["latency_s"], 2))
        print("decision:", json.dumps(st.get("decision"), default=str)[:300])
        print("fit:", st.get("fit_report", {}).get("score"), "| risk:", st.get("risk_report", {}).get("score"))
        print("price:", json.dumps(st.get("price_quote"), default=str)[:300])
        print("claims:", st.get("claim_stats"))
        print("draft:\n", st.get("proposal_draft", {}).get("cover_letter"))
        print("pending approval keys:", list((last.get("pending") or {}).keys()))
        if last.get("interrupted"):
            done = [e async for e in env.runtime.resume(f"bid:eval-{persona}:{job_id}", {"action": "approve"})]
            print("after approve:", done[-1]["state"].get("status"), done[-1]["state"].get("submission"))


if __name__ == "__main__":
    asyncio.run(main(*(sys.argv[1:3])))
