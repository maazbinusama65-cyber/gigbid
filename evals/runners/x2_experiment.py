"""X2 signature extension: proposal A/B experiment inside GigSim.

    python -m evals.runners.x2_experiment [--persona all] [--n 40] [--profile stub]

Every job in a fixed set is bid on once under each strategy, in separate simulator resets with the same seed, so a
client's decision differs only because of the proposal. Reply = reply, interview or hire. We report the
unpaired two-proportion z-test and the paired exact McNemar test (the design is paired), with Wilson intervals.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import shutil

from agent.config_loader import ROOT, load_config
from evals import metrics as M
from evals.runners.common import PERSONAS, write_result
from evals.runners.gigsim_outcomes import run_persona


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact p for discordant pairs b (A only replied) and c (B only replied)."""
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2**n
    return round(min(1.0, 2 * tail), 6)


def compare(a: dict, b: dict, name_a: str, name_b: str) -> dict:
    sa = {p["job_id"]: p["replied"] for p in a["per_proposal"]}
    sb = {p["job_id"]: p["replied"] for p in b["per_proposal"]}
    paired = sorted(set(sa) & set(sb))
    only_a = sum(sa[j] and not sb[j] for j in paired)
    only_b = sum(sb[j] and not sa[j] for j in paired)
    both = sum(sa[j] and sb[j] for j in paired)
    return {
        name_a: {"n": a["proposals_submitted"], "replied": a["replied"], "rate": a["reply_rate"],
                 "ci95": a["reply_rate_ci95"], "connects_per_reply": a["connects_per_reply"]},
        name_b: {"n": b["proposals_submitted"], "replied": b["replied"], "rate": b["reply_rate"],
                 "ci95": b["reply_rate_ci95"], "connects_per_reply": b["connects_per_reply"]},
        "unpaired_z_test": M.two_proportion_z(a["replied"], a["proposals_submitted"], b["replied"], b["proposals_submitted"]),
        "paired": {"n_pairs": len(paired), "both_replied": both, f"only_{name_a}": only_a, f"only_{name_b}": only_b,
                   "mcnemar_exact_p": mcnemar_exact(only_a, only_b)},
    }


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="all")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--profile", default="stub")
    a = ap.parse_args()
    exp = load_config()["experiments"]
    name_a, name_b = exp["strategies"][:2]
    tmp = ROOT / "data" / "processed" / "x2_tmp"
    out: dict = {"profile": a.profile, "strategies": [name_a, name_b], "seed": exp["seed"], "n_per_persona": a.n,
                 "per_persona": {}}
    tot = {name_a: [0, 0], name_b: [0, 0]}
    pooled_pairs = {"a": 0, "b": 0}
    for p in (PERSONAS if a.persona == "all" else (a.persona,)):
        ra = await run_persona(p, a.n, a.profile, name_a, None, tmp / f"{p}-a")
        rb = await run_persona(p, a.n, a.profile, name_b, None, tmp / f"{p}-b")
        cmp_ = compare(ra, rb, name_a, name_b)
        out["per_persona"][p] = cmp_
        for nm, r in ((name_a, ra), (name_b, rb)):
            tot[nm][0] += r["replied"]
            tot[nm][1] += r["proposals_submitted"]
        pooled_pairs["a"] += cmp_["paired"][f"only_{name_a}"]
        pooled_pairs["b"] += cmp_["paired"][f"only_{name_b}"]
        print(p, cmp_["unpaired_z_test"], cmp_["paired"], flush=True)
    out["pooled"] = {nm: {"replied": x, "n": n, "rate": round(x / n, 4) if n else None, "ci95": M.wilson(x, n)}
                     for nm, (x, n) in tot.items()}
    out["pooled"]["unpaired_z_test"] = M.two_proportion_z(*tot[name_a], *tot[name_b])
    out["pooled"]["mcnemar_exact_p"] = mcnemar_exact(pooled_pairs["a"], pooled_pairs["b"])
    print("wrote", write_result("x2_experiment.json", out))
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
