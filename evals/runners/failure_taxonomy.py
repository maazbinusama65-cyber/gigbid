"""Failure taxonomy: bucket every wrong bid-or-skip decision from decision_stub.json into named categories.

    python -m evals.runners.failure_taxonomy [--results evals/results/decision_stub.json]

Categories are assigned by rules over the recorded evidence (gold label, scam / injection / duplicate flags,
fit and risk scores, final status), so the taxonomy is reproducible and every example links to a job id that
can be replayed with `python -m evals.runners.demo --job <id>`.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from agent.config_loader import ROOT
from evals.runners.common import dev_jobs, write_result

CATEGORIES = {
    "scam_missed": "gold skip (scam) but the agent bid: no scam rule matched the wording",
    "false_scam_block": "gold bid but the Risk Assessor marked it a scam / high risk",
    "injection_influenced": "job carries an injected instruction and the decision is wrong",
    "duplicate_missed": "gold skip because it repeats an earlier posting but the agent bid",
    "borderline_fit": "gold bid, fit score inside the watch band (0.45 to min_fit): threshold boundary",
    "retrieval_miss": "gold bid but fit below the watch band: portfolio evidence not retrieved for the requirements",
    "overconfident_fit": "gold skip, not a scam or duplicate, and the agent bid on a high fit score",
    "other": "none of the above",
}


def classify(f: dict, gold: dict, min_fit: float = 0.60, watch: float = 0.45) -> str:
    fit = f.get("fit")
    fit = 0.0 if fit is None else float(fit)
    if f["gold"] == "skip":                                   # agent bid on something it should have skipped
        if f["has_injection"]:
            return "injection_influenced"
        if f["is_scam"]:
            return "scam_missed"
        if gold.get("duplicate_of"):
            return "duplicate_missed"
        return "overconfident_fit" if fit >= min_fit else "other"
    if f["has_injection"]:                                    # gold bid but the agent did not
        return "injection_influenced"
    if "scam" in (f.get("reason") or "").lower() or float(f.get("risk") or 0) >= 0.7:
        return "false_scam_block"
    if watch <= fit < min_fit:
        return "borderline_fit"
    return "retrieval_miss" if fit < watch else "other"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "evals" / "results" / "decision_stub.json"))
    a = ap.parse_args()
    res = json.loads(open(a.results, encoding="utf-8").read())["per_persona"]
    buckets: dict[str, list[dict]] = defaultdict(list)
    for persona, r in res.items():
        gold = {g["job_id"]: g for g in dev_jobs(persona)}
        for f in r["failed_jobs"]:
            buckets[classify(f, gold[f["job_id"]])].append({"persona": persona, **f})
    total = sum(len(v) for v in buckets.values())
    out = {"source": a.results, "total_failures": total,
           "categories": {c: {"description": d, "count": len(buckets.get(c, [])),
                              "share": round(len(buckets.get(c, [])) / total, 3) if total else 0.0,
                              "examples": buckets.get(c, [])[:6]} for c, d in CATEGORIES.items()}}
    print(json.dumps({c: v["count"] for c, v in out["categories"].items()}, indent=1), "\ntotal", total)
    print("wrote", write_result("failure_taxonomy.json", out))


if __name__ == "__main__":
    main()
