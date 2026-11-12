"""Calibrate V8's grading thresholds on a calibration slice of the dev sets (every 5th job).

    python -m evals.runners.rag_calibrate

Runs the corrective loop with `strong=9` (always re-query twice, so each requirement gets its best
support over three attempts) and `weak=0` (never refuse), then grid-searches `weak` (below it a
requirement is 'none') and `min_coverage` (refuse the job when fewer requirements are covered) to
maximise balanced accuracy of refusing gold-empty jobs while not refusing gold jobs. Only the
calibration jobs are used; rag_eval reports V8 both on all jobs and excluding them.
Writes evals/results/rag_v8_calibration.json.
"""
from __future__ import annotations

import json
import logging

from evals.runners import rag_eval
from rag import config
from rag.embedder import get_embedder
from rag.retriever import build_index, get_retriever

log = logging.getLogger("rag_calibrate")


def collect(personas: list[str]) -> list[dict]:
    embedder = get_embedder()
    rows = []
    for p in personas:
        idx = build_index(p, embedder=embedder)
        retr = get_retriever("v8_corrective", index=idx,
                             cfg={"corrective": {"strong": 9.0, "weak": 0.0, "min_coverage": 0.0}})
        for row in rag_eval.load_eval_data(p, rag_eval.REPO / "evals" / "datasets",
                                           rag_eval.REPO / "data" / "gigsim_seed" / "jobs.jsonl"):
            if not rag_eval.is_calibration(row["job_id"]):
                continue
            res = retr.search_job_detailed(row["job"], k=5)
            rows.append({"persona": p, "job_id": row["job_id"], "has_gold": bool(
                row["gold_project_ids"]), "support": list(res["trace"]["support"].values())})
    return rows


def grid(rows: list[dict]) -> list[dict]:
    out = []
    empty = [r for r in rows if not r["has_gold"]]
    full = [r for r in rows if r["has_gold"]]
    for weak in [x / 100 for x in range(40, 80, 2)]:
        for cov in (0.2, 0.34, 0.5, 0.67, 0.8, 1.0):
            def refused(r, weak=weak, cov=cov):
                sup = r["support"]
                return sum(s >= weak for s in sup) / max(len(sup), 1) < cov

            rec = sum(refused(r) for r in empty) / max(len(empty), 1)
            false = sum(refused(r) for r in full) / max(len(full), 1)
            out.append({"weak": weak, "min_coverage": cov, "refusal_recall": rec,
                        "false_refusal": false, "balanced_accuracy": (rec + 1 - false) / 2})
    return sorted(out, key=lambda r: (-r["balanced_accuracy"], r["false_refusal"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    personas = [p for p in rag_eval.PERSONAS
                if (rag_eval.REPO / "evals" / "datasets" / f"dev_{p}.jsonl").exists()]
    rows = collect(personas)
    ranked = grid(rows)
    best = ranked[0]
    report = {"n_jobs": len(rows), "n_gold_empty": sum(not r["has_gold"] for r in rows),
              "chosen": {**best, "strong": round(best["weak"] + 0.08, 2)}, "top5": ranked[:5],
              "mean_best_support": {
                  "gold_empty": _mean([s for r in rows if not r["has_gold"] for s in r["support"]]),
                  "gold": _mean([s for r in rows if r["has_gold"] for s in r["support"]])}}
    (config.REPO_ROOT / "evals" / "results" / "rag_v8_calibration.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


if __name__ == "__main__":
    main()
