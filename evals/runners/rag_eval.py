"""B4 retrieval evaluation: every RAG variant on the dev sets, per persona.

    python -m evals.runners.rag_eval            # full run (real embedder), writes evals/results/
    python -m evals.runners.rag_eval --smoke    # 30 jobs total, for CI
    RAG_EMBEDDER=hash python -m evals.runners.rag_eval --smoke   # fully offline (NOT real numbers)

Protocol (see also docs/rag_results_note.md)
  * Data: evals/datasets/dev_<persona>.jsonl joined with the job text in
    data/gigsim_seed/jobs.jsonl; persona corpora under data/personas/<persona>/.
  * Per job the retriever returns up to 50 evidence items (no per-project cap); items are
    collapsed to a ranked list of distinct projects (rag/metrics.py). A past proposal credits all
    projects it cites. CV items and generic proposals credit nothing.
  * Metrics are computed on jobs with at least one gold project (n_eval): project-level
    Recall@5 (hits / |gold|), capped recall (hits / min(|gold|, 5)), MRR and nDCG@10.
    Refusals (V8) return no evidence and therefore score 0 on gold jobs; refusal precision/recall
    against the gold-empty ("should skip") jobs is reported separately.
  * Requirements for decomposition come from the deterministic heuristic extractor on the job
    description (no gold requirements are used); `requirements_overlap` reports how often it
    reproduces the dataset's requirement list, as a sanity check.
  * Latency: p50/p95 of a COLD retrieval (query-embedding and reranker caches cleared) on a
    sample of jobs; excludes index build time.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import platform
import random
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag import config
from rag.embedder import get_embedder
from rag.metrics import job_metrics, mean, paired_bootstrap, percentile
from rag.query import extract_requirements
from rag.rerank import get_reranker
from rag.retriever import build_index, get_retriever

log = logging.getLogger("rag_eval")
REPO = config.REPO_ROOT
PERSONAS = ("ai_ml", "fullstack", "data_analyst")

# Pre-registered BEFORE any number is produced (committed in code, written first in the results).
HYPOTHESIS = {
    "id": "H1",
    "statement": ("Requirement decomposition plus hybrid retrieval (v1_decompose+v2_hybrid) raises "
                  "project-level evidence Recall@5 by >= 15 points over V0 (v0_naive) on jobs "
                  "with >= 4 requirements."),
    "variant": "v1_decompose+v2_hybrid",
    "baseline": "v0_naive",
    "metric": "recall5",
    "min_gain_points": 15.0,
    "subset": "n_requirements >= 4, jobs with >= 1 gold project",
    "secondary": ("Cross-encoder reranking (v3_rerank) improves nDCG@10 over v0b_naive_struct; "
                  "outcome-aware ranking (v4) does not improve Recall@5 because gold is defined by "
                  "requirement fit, not by what won."),
}

SINGLE = ["v0_naive", "v0b_naive_struct", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome",
          "v5_multivector", "v6_contextual", "v7_hyde", "v8_corrective", "v9_skill_graph"]
COMPOSED = ["v1_decompose+v2_hybrid", "v1_decompose+v2_hybrid+v3_rerank",
            "v1_decompose+v2_hybrid+v3_rerank+v4_outcome",
            "v1_decompose+v2_hybrid+v3_rerank+v9_skill_graph",
            "v1_decompose+v2_hybrid+v3_rerank+v8_corrective"]
DEFAULT_VARIANTS = SINGLE + COMPOSED
N_BUCKETS = (("1-3", 1, 3), ("4-5", 4, 5), ("6+", 6, 99))
LATENCY_SAMPLE = 12


# ----------------------------------------------------------------------------- data
def _read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_eval_data(persona: str, dev_dir: Path, jobs_path: Path) -> list[dict]:
    """Dev rows joined with the job object -> [{**dev_row, "job": job}]."""
    jobs = {j["job_id"]: j for j in _read_jsonl(jobs_path)}
    out = []
    for row in _read_jsonl(dev_dir / f"dev_{persona}.jsonl"):
        job = jobs.get(row["job_id"])
        if job is None:
            log.warning("job %s missing from %s", row["job_id"], jobs_path)
            continue
        out.append({**row, "job": job})
    return out


def smoke_subset(rows: list[dict], n: int) -> list[dict]:
    """Deterministic subset with a stride, keeping both gold and gold-empty jobs."""
    if len(rows) <= n:
        return rows
    step = len(rows) / n
    return [rows[int(i * step)] for i in range(n)]


def bucket(n_req: int) -> str:
    for name, lo, hi in N_BUCKETS:
        if lo <= n_req <= hi:
            return name
    return "6+"


# ----------------------------------------------------------------------------- scoring
def aggregate(records: list[dict]) -> dict[str, Any]:
    """Aggregate per-job records (with gold) into the metric block."""
    gold_jobs = [r for r in records if r["gold"]]
    out = {"n_eval": len(gold_jobs),
           "recall5": mean([r["recall5"] for r in gold_jobs]),
           "recall5_capped": mean([r["recall5_capped"] for r in gold_jobs]),
           "mrr": mean([r["mrr"] for r in gold_jobs]),
           "ndcg10": mean([r["ndcg10"] for r in gold_jobs])}
    return out


def is_calibration(job_id: str) -> bool:
    """Every 5th dev job (by numeric id suffix) is reserved for tuning V8's thresholds."""
    m = re.search(r"(\d+)$", job_id)
    return bool(m) and int(m.group(1)) % 5 == 0


def refusal_block(records: list[dict]) -> dict[str, Any]:
    empty = [r for r in records if not r["gold"]]
    has = [r for r in records if r["gold"]]
    return {"n_gold_empty": len(empty), "n_gold": len(has),
            "refused_on_gold_empty": sum(r["refused"] for r in empty),
            "refused_on_gold": sum(r["refused"] for r in has),
            "refusal_recall": (sum(r["refused"] for r in empty) / len(empty)) if empty else None,
            "false_refusal_rate": (sum(r["refused"] for r in has) / len(has)) if has else None}


def evaluate_variant(variant: str, data: dict[str, list[dict]], indexes: dict,
                     proposal_credit: str = "all") -> list[dict]:
    """Run one variant on every persona's jobs -> flat list of per-job records."""
    records = []
    for persona, rows in data.items():
        retr = get_retriever(variant, index=indexes[persona])
        for row in rows:
            res = retr.search_job_detailed(row["job"], k=50, max_per_project=None)
            gold = set(row["gold_project_ids"])
            m = job_metrics(res["items"], gold, proposal_credit)
            records.append({"variant": variant, "persona": persona, "job_id": row["job_id"],
                            "job_type": row["job_type"], "n_requirements": row["n_requirements"],
                            "bucket": bucket(row["n_requirements"]), "gold": sorted(gold),
                            "refused": res["refused"], "uncovered": res["uncovered"], **m})
    return records


def measure_latency(variant: str, data: dict[str, list[dict]], indexes: dict) -> dict[str, float]:
    """Cold per-job retrieval latency (caches cleared before every job)."""
    emb = get_embedder()
    rr = None
    times: list[float] = []
    for persona, rows in data.items():
        retr = get_retriever(variant, index=indexes[persona])
        for row in rows[:LATENCY_SAMPLE]:
            if hasattr(emb, "_qcache"):
                emb._qcache.clear()
            if retr.spec.rerank:
                rr = get_reranker()
                if hasattr(rr, "_cache"):
                    rr._cache.clear()
            t0 = time.perf_counter()
            retr.search_job(row["job"], k=5)
            times.append((time.perf_counter() - t0) * 1000)
    return {"p50_ms": percentile(times, 0.5), "p95_ms": percentile(times, 0.95),
            "n": len(times)}


def summarise(variant: str, records: list[dict], latency: dict | None) -> dict[str, Any]:
    from rag.variants import spec_from_name

    def group(key_fn) -> dict[str, Any]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            groups[key_fn(r)].append(r)
        return {k: aggregate(v) for k, v in sorted(groups.items())}

    ge4 = [r for r in records if r["n_requirements"] >= 4]
    return {"variant": variant, "components": spec_from_name(variant).components(),
            "overall": aggregate(records),
            "overall_excluding_calibration": aggregate(
                [r for r in records if not is_calibration(r["job_id"])]),
            "refusal_excluding_calibration": refusal_block(
                [r for r in records if not is_calibration(r["job_id"])]),
            "n_requirements_ge4": aggregate(ge4),
            "by_persona": group(lambda r: r["persona"]),
            "by_job_type": group(lambda r: r["job_type"]),
            "by_n_requirements": group(lambda r: r["bucket"]),
            "refusal": refusal_block(records), "latency_cold": latency}


def hypothesis_test(per_variant: dict[str, list[dict]]) -> dict[str, Any]:
    h = HYPOTHESIS
    if h["variant"] not in per_variant or h["baseline"] not in per_variant:
        return {"status": "not evaluated (variant missing from this run)"}
    base = {(r["persona"], r["job_id"]): r for r in per_variant[h["baseline"]]}
    diffs, base_vals, var_vals = [], [], []
    for r in per_variant[h["variant"]]:
        b = base[(r["persona"], r["job_id"])]
        if r["gold"] and r["n_requirements"] >= 4:
            diffs.append(r[h["metric"]] - b[h["metric"]])
            base_vals.append(b[h["metric"]])
            var_vals.append(r[h["metric"]])
    d, lo, hi = paired_bootstrap(diffs)
    return {"hypothesis_id": h["id"], "n_jobs": len(diffs), "baseline_recall5": mean(base_vals),
            "variant_recall5": mean(var_vals), "gain_points": 100 * d,
            "ci95_points": [100 * lo, 100 * hi],
            "verdict": ("SUPPORTED" if 100 * d >= h["min_gain_points"] and lo > 0 else
                        "NOT SUPPORTED" if 100 * d < h["min_gain_points"] else
                        "gain >= threshold but CI crosses 0")}


# ----------------------------------------------------------------------------- outputs
def _fmt(x: float | None, pct: bool = True) -> str:
    if x is None or x != x:
        return "n/a"
    return f"{100 * x:.1f}" if pct else f"{x:.3f}"


def markdown_table(summaries: dict[str, dict]) -> str:
    lines = ["| Variant | Recall@5 | Recall@5 (capped) | MRR | nDCG@10 | Recall@5 (>=4 reqs) | "
             "p50 ms | p95 ms | refusal recall / false refusal |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, s in summaries.items():
        o, g4, lat, rf = s["overall"], s["n_requirements_ge4"], s["latency_cold"] or {}, s["refusal"]
        refusal = "-"
        if rf["refused_on_gold_empty"] or rf["refused_on_gold"]:
            refusal = f"{_fmt(rf['refusal_recall'])} / {_fmt(rf['false_refusal_rate'])}"
        lines.append(f"| {name} | {_fmt(o['recall5'])} | {_fmt(o['recall5_capped'])} | "
                     f"{_fmt(o['mrr'], False)} | {_fmt(o['ndcg10'], False)} | {_fmt(g4['recall5'])} | "
                     f"{lat.get('p50_ms', float('nan')):.0f} | {lat.get('p95_ms', float('nan')):.0f} | "
                     f"{refusal} |")
    return "\n".join(lines)


def write_csv(path: Path, summaries: dict[str, dict]) -> None:
    cols = ["variant", "slice", "value", "n_eval", "recall5", "recall5_capped", "mrr", "ndcg10"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for name, s in summaries.items():
            blocks = [("overall", "all", s["overall"]), ("n_requirements_ge4", ">=4", s["n_requirements_ge4"])]
            for key in ("by_persona", "by_job_type", "by_n_requirements"):
                blocks += [(key, k, v) for k, v in s[key].items()]
            for slice_name, value, m in blocks:
                w.writerow([name, slice_name, value, m["n_eval"], *(f"{m[c]:.4f}" for c in
                                                                   cols[4:])])


def write_outputs(out_dir: Path, prefix: str, payload: dict, summaries: dict[str, dict],
                  per_job: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # `hypothesis` is the first key: it is committed in code and written before any number.
    (out_dir / f"{prefix}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    write_csv(out_dir / f"{prefix}.csv", summaries)
    md = ["# RAG variants (dev sets)", "", f"**Hypothesis (pre-registered):** {HYPOTHESIS['statement']}",
          "", markdown_table(summaries), "", "## Hypothesis test", "",
          "```json", json.dumps(payload["hypothesis_test"], indent=1), "```"]
    (out_dir / f"{prefix}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with open(out_dir / f"{prefix}_per_job.jsonl", "w", encoding="utf-8") as fh:
        for r in per_job:
            fh.write(json.dumps(r) + "\n")


def requirements_overlap(data: dict[str, list[dict]]) -> float:
    """Fraction of dev requirement strings reproduced (as substrings) by the heuristic extractor."""
    hit = tot = 0
    for rows in data.values():
        for row in rows:
            got = " | ".join(extract_requirements(row["job"], 20)).lower()
            for req in row["requirements"]:
                tot += 1
                hit += req.lower().rstrip(" .") in got
    return hit / tot if tot else float("nan")


# ----------------------------------------------------------------------------- main
def run(personas: list[str], variants: list[str], *, dev_dir: Path, jobs_path: Path,
        personas_dir: Path, index_root: Path, out_dir: Path, prefix: str, smoke: bool = False,
        proposal_credit: str = "all", latency: bool = True) -> dict:
    embedder = get_embedder()
    data, indexes = {}, {}
    for p in personas:
        rows = load_eval_data(p, dev_dir, jobs_path)
        data[p] = smoke_subset(rows, 10) if smoke else rows
        indexes[p] = build_index(p, embedder=embedder, personas_dir=personas_dir,
                                 index_root=index_root)
        log.info("%s: %d jobs, index %s", p, len(data[p]), indexes[p].stats())
    payload: dict[str, Any] = {
        "hypothesis": HYPOTHESIS,
        "protocol": {"smoke": smoke, "proposal_credit": proposal_credit,
                     "k_retrieved": 50, "embedder": embedder.name,
                     "reranker": config.reranker_model(), "personas": personas,
                     "n_jobs": {p: len(r) for p, r in data.items()},
                     "n_eval_jobs": {p: sum(bool(r["gold_project_ids"]) for r in rows)
                                     for p, rows in data.items()},
                     "requirements_overlap": requirements_overlap(data),
                     "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                     "python": platform.python_version(),
                     "index": {p: indexes[p].stats() for p in personas}},
    }
    summaries: dict[str, dict] = {}
    per_variant: dict[str, list[dict]] = {}
    per_job: list[dict] = []
    for v in variants:
        t0 = time.time()
        records = evaluate_variant(v, data, indexes, proposal_credit)
        lat = measure_latency(v, data, indexes) if latency else None
        per_variant[v] = records
        per_job += records
        summaries[v] = summarise(v, records, lat)
        o = summaries[v]["overall"]
        log.info("%-60s R@5=%.3f MRR=%.3f nDCG=%.3f (%.0fs)", v, o["recall5"], o["mrr"],
                 o["ndcg10"], time.time() - t0)
    payload["hypothesis_test"] = hypothesis_test(per_variant)
    payload["variants"] = summaries
    write_outputs(out_dir, prefix, payload, summaries, per_job)
    return payload


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--smoke", action="store_true", help="10 jobs per persona (30 total)")
    ap.add_argument("--personas", nargs="*", default=None)
    ap.add_argument("--variants", nargs="*", default=None)
    ap.add_argument("--dev-dir", type=Path, default=REPO / "evals" / "datasets")
    ap.add_argument("--jobs", type=Path, default=REPO / "data" / "gigsim_seed" / "jobs.jsonl")
    ap.add_argument("--personas-dir", type=Path, default=config.personas_root())
    ap.add_argument("--index-root", type=Path, default=config.index_root())
    ap.add_argument("--out-dir", type=Path, default=REPO / "evals" / "results")
    ap.add_argument("--proposal-credit", choices=["all", "first", "none"], default="all")
    ap.add_argument("--no-latency", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    personas = args.personas or [p for p in PERSONAS if (args.dev_dir / f"dev_{p}.jsonl").exists()]
    random.seed(0)
    run(personas, args.variants or DEFAULT_VARIANTS, dev_dir=args.dev_dir, jobs_path=args.jobs,
        personas_dir=args.personas_dir, index_root=args.index_root, out_dir=args.out_dir,
        prefix="rag_smoke" if args.smoke else "rag_variants", smoke=args.smoke,
        proposal_credit=args.proposal_credit, latency=not args.no_latency)


if __name__ == "__main__":
    main()
