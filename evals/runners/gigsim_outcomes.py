"""Outcome evaluation: a fixed set of jobs is bid on (the "user" approves every proposal the graph
drafts), GigSim's simulated clients decide, and we report reply / interview / hire rates (B4 "Outcome").

    python -m evals.runners.gigsim_outcomes [--persona ai_ml] [--n 40] [--style-variant evidence_dense]
                                            [--rag-variant v3_rerank] [--profile stub] [--tag x]

Clients are deterministic given GigSim's seed, so two configurations are compared on identical jobs.
The simulator runs with an enlarged Connects balance (policy is data) so the Connects budget does not
truncate the experiment; Connects spent per outcome is still reported.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path

import httpx

from agent.config_loader import ROOT
from evals import metrics as M
from evals.harness import eval_env, load_profile, run_job
from evals.runners.common import PERSONAS, dev_jobs, seed_jobs, write_result

TICK_HOURS = 24 * 21


def _policy_copy(tmp: Path) -> Path:
    data = json.loads((ROOT / "gigsim" / "policy.json").read_text(encoding="utf-8"))
    data.update(initial_balance=100000, max_balance=100000)
    p = tmp / "policy_eval.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def pick_jobs(persona: str, n: int) -> list[str]:
    """Fixed job set: gold-bid, non-scam, non-duplicate jobs in posting order (same for every config)."""
    posted = {j["job_id"]: j["posted_at"] for j in seed_jobs().values() if j.get("kind") == "dev"}
    gold = [g for g in dev_jobs(persona) if g["label"] == "bid" and not g["is_scam"] and not g["duplicate_of"]]
    gold.sort(key=lambda g: posted.get(g["job_id"], ""))
    return [g["job_id"] for g in gold[:n]]


async def run_persona(persona: str, n: int, profile: str, style_variant: str | None, rag_variant: str | None,
                      tmp: Path, overrides: dict | None = None) -> dict:
    prof = load_profile(persona)
    settings = {"min_project_budget_usd": prof["min_project_budget_usd"], "hourly_rate_usd": prof["hourly_rate_usd"],
                **({"style_variant": style_variant} if style_variant else {})}
    jobs = pick_jobs(persona, n)
    tmp.mkdir(parents=True, exist_ok=True)
    async with eval_env(profile, persona, tmp=tmp, rag_variant=rag_variant, overrides=overrides,
                        gigsim_env={"GIGSIM_POLICY_PATH": str(_policy_copy(tmp))}) as env:
        submitted = []
        for jid in jobs:                                  # sequential: Connects and feed order matter
            last = await run_job(env, persona, jid, settings)
            if not last.get("interrupted"):
                continue
            thread = f"bid:eval-{persona}:{jid}"
            done = [e async for e in env.runtime.resume(thread, {"action": "approve"})]
            st = done[-1].get("state", {})
            if st.get("status") == "submitted":
                submitted.append((jid, st["submission"]["proposal_id"], st["submission"].get("connects_spent") or 0))
        async with httpx.AsyncClient(base_url=env.gigsim_url, headers=env.headers(persona), timeout=60) as c:
            await c.post("/v1/sim/tick", json={"steps": TICK_HOURS})
            events = (await c.get("/v1/events", params={"since": 0})).json()
        # The final status hides replies (an unanswered reply is marked "lost" after 72 simulated hours), so
        # outcomes are read from the event log: a proposal "replied" if any of its events says so.
        seen: dict[str, set[str]] = {}
        for e in events:
            seen.setdefault(e.get("proposal_id") or "", set()).add(e["type"])
        statuses = [("hired" if "hired" in seen.get(pid, ()) else "interview" if "interview" in seen.get(pid, ())
                     else "replied" if "replied" in seen.get(pid, ()) else "viewed" if "viewed" in seen.get(pid, ())
                     else "no_response") for _, pid, _ in submitted]
    n_sub = len(submitted)
    replied = sum(s in ("replied", "interview", "hired") for s in statuses)
    interview = sum(s in ("interview", "hired") for s in statuses)
    hired = sum(s == "hired" for s in statuses)
    spent = sum(c for _, _, c in submitted)
    return {"persona": persona, "jobs_in_set": len(jobs), "proposals_submitted": n_sub, "replied": replied,
            "interview": interview, "hired": hired,
            "reply_rate": round(replied / n_sub, 4) if n_sub else None,
            "reply_rate_ci95": M.wilson(replied, n_sub), "hire_rate": round(hired / n_sub, 4) if n_sub else None,
            "connects_spent": spent, "connects_per_reply": round(spent / replied, 2) if replied else None,
            "status_counts": {s: statuses.count(s) for s in sorted(set(statuses))},
            "viewed": sum(s != "no_response" for s in statuses),
            "note": "interview/hire need the freelancer to answer within 72 simulated hours; this batch run never "
                    "answers, so only reply rate is a meaningful outcome here",
            "per_proposal": [{"job_id": j, "status": s, "replied": s in ("replied", "interview", "hired")}
                             for (j, _, _), s in zip(submitted, statuses, strict=True)]}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="all")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--profile", default="stub")
    ap.add_argument("--style-variant", default=None)
    ap.add_argument("--rag-variant", default=None)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    tmp = ROOT / "data" / "processed" / "outcomes_tmp"
    out = {"profile": a.profile, "style_variant": a.style_variant or "default", "rag_variant": a.rag_variant or "config",
           "per_persona": {}}
    for p in (PERSONAS if a.persona == "all" else (a.persona,)):
        out["per_persona"][p] = await run_persona(p, a.n, a.profile, a.style_variant, a.rag_variant, tmp / p)
        r = out["per_persona"][p]
        print(f"{p}: submitted {r['proposals_submitted']} reply {r['reply_rate']} hire {r['hire_rate']}", flush=True)
    tot_sub = sum(r["proposals_submitted"] for r in out["per_persona"].values())
    tot_rep = sum(r["replied"] for r in out["per_persona"].values())
    tot_hire = sum(r["hired"] for r in out["per_persona"].values())
    out["overall"] = {"proposals_submitted": tot_sub, "reply_rate": round(tot_rep / tot_sub, 4) if tot_sub else None,
                      "hire_rate": round(tot_hire / tot_sub, 4) if tot_sub else None,
                      "reply_rate_ci95": M.wilson(tot_rep, tot_sub)}
    name = f"gigsim_outcomes_{a.profile}{('_' + a.tag) if a.tag else ''}.json"
    print("wrote", write_result(name, out))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
