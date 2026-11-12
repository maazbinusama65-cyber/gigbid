"""R&D question B ablation: take the best pipeline and remove one component at a time.

    python -m evals.runners.ablation                      # best pipeline from rag_variants.json
    python -m evals.runners.ablation --pipeline "v1_decompose+v2_hybrid+v3_rerank"

The best pipeline is chosen by overall Recall@5 (ties: nDCG@10) among everything evaluated in
evals/results/rag_variants.json. NOTE this selection and the ablation use the same dev jobs, so
treat the winner's absolute numbers as optimistic; the deltas between ablated pipelines are the
point. Each delta is a paired difference on identical jobs with a 95% bootstrap CI.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from evals.runners import rag_eval
from rag import config
from rag.embedder import get_embedder
from rag.metrics import mean, paired_bootstrap
from rag.pipeline import PipelineSpec
from rag.retriever import build_index
from rag.variants import spec_from_name

log = logging.getLogger("ablation")

# Pre-registered in code before the ablation was run.
ABLATION_HYPOTHESIS = {
    "id": "H2",
    "statement": ("In the best pipeline, removing requirement decomposition causes the largest "
                  "Recall@5 drop of any single component; removing the cross-encoder reranker "
                  "costs MRR/nDCG@10 more than Recall@5."),
    "falsified_if": ("another component's removal drops Recall@5 by more than decomposition's, or "
                     "the reranker's Recall@5 drop exceeds its MRR drop."),
}

# component -> function(spec) returning the spec with that component removed (None if not present)
def _remove(spec: PipelineSpec) -> dict[str, PipelineSpec]:
    out: dict[str, PipelineSpec] = {}
    if spec.query == "decompose":
        out["query decomposition (decompose -> whole post)"] = spec.with_(query="whole")
    if spec.query == "hyde":
        out["HyDE (hyde -> whole post)"] = spec.with_(query="whole")
    if spec.retrieval == "hybrid":
        out["BM25 hybrid (hybrid -> dense only)"] = spec.with_(retrieval="dense")
    if spec.rerank:
        out["cross-encoder rerank"] = spec.with_(rerank=False)
    if spec.outcome:
        out["outcome-aware boost"] = spec.with_(outcome=False)
    if spec.graph:
        out["skill graph fusion"] = spec.with_(graph=False)
    if spec.corrective:
        out["corrective loop"] = spec.with_(corrective=False)
    if spec.scheme in ("ctx", "mv"):
        out[f"{spec.scheme} indexing (-> plain structure chunks)"] = spec.with_(scheme="struct")
    if spec.scheme in ("struct", "ctx", "mv"):
        out["structure-aware chunking (-> fixed chunks)"] = spec.with_(scheme="fixed")
    return out


def best_variant(results_path: Path) -> str:
    variants = json.loads(results_path.read_text(encoding="utf-8"))["variants"]
    return max(variants, key=lambda v: (variants[v]["overall"]["recall5"],
                                        variants[v]["overall"]["ndcg10"]))


def _by_job(records: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["persona"], r["job_id"]): r for r in records if r["gold"]}


def run(pipeline: str, *, personas: list[str], dev_dir: Path, jobs_path: Path,
        personas_dir: Path, index_root: Path, out_dir: Path, smoke: bool = False) -> dict:
    embedder = get_embedder()
    data, indexes = {}, {}
    for p in personas:
        rows = rag_eval.load_eval_data(p, dev_dir, jobs_path)
        data[p] = rag_eval.smoke_subset(rows, 10) if smoke else rows
        indexes[p] = build_index(p, embedder=embedder, personas_dir=personas_dir,
                                 index_root=index_root)
    full_spec = spec_from_name(pipeline)
    full = _by_job(rag_eval.evaluate_variant(pipeline, data, indexes))
    rows = []
    for label, spec in _remove(full_spec).items():
        name = spec.label()
        ablated = _by_job(rag_eval.evaluate_variant(name, data, indexes))
        entry = {"removed": label, "pipeline": name}
        for metric in ("recall5", "mrr", "ndcg10"):
            diffs = [ablated[k][metric] - full[k][metric] for k in full]
            d, lo, hi = paired_bootstrap(diffs)
            entry[metric] = mean([ablated[k][metric] for k in full])
            entry[f"{metric}_delta_points"] = 100 * d
            entry[f"{metric}_delta_ci95"] = [100 * lo, 100 * hi]
        rows.append(entry)
        log.info("%-55s dR@5=%+.1f dMRR=%+.1f dnDCG=%+.1f", label, entry["recall5_delta_points"],
                 entry["mrr_delta_points"], entry["ndcg10_delta_points"])
    payload = {
        "hypothesis": ABLATION_HYPOTHESIS,
        "best_pipeline": {"name": pipeline, "components": full_spec.components(),
                          "n_eval_jobs": len(full),
                          **{m: mean([r[m] for r in full.values()])
                             for m in ("recall5", "mrr", "ndcg10")}},
        "selection_note": "winner chosen on the same dev jobs it is ablated on",
        "ablations": sorted(rows, key=lambda r: r["recall5_delta_points"]),
        "protocol": {"embedder": embedder.name, "smoke": smoke, "personas": personas},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = "rag_ablation_smoke" if smoke else "rag_ablation"
    (out_dir / f"{stem}.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")
    with open(out_dir / f"{stem}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["removed", "pipeline", "recall5", "recall5_delta_pts", "mrr", "mrr_delta_pts",
                    "ndcg10", "ndcg10_delta_pts"])
        for r in payload["ablations"]:
            w.writerow([r["removed"], r["pipeline"], f"{r['recall5']:.4f}",
                        f"{r['recall5_delta_points']:.2f}", f"{r['mrr']:.4f}",
                        f"{r['mrr_delta_points']:.2f}", f"{r['ndcg10']:.4f}",
                        f"{r['ndcg10_delta_points']:.2f}"])
    best = payload["best_pipeline"]
    md = [f"# Ablation of `{pipeline}`", "",
          f"**Hypothesis (pre-registered):** {ABLATION_HYPOTHESIS['statement']}", "",
          f"Full pipeline: Recall@5 {100 * best['recall5']:.1f}, MRR {best['mrr']:.3f}, "
          f"nDCG@10 {best['ndcg10']:.3f} (n={best['n_eval_jobs']}).", "",
          "| Component removed | Recall@5 | Δ points [95% CI] | MRR | Δ points | nDCG@10 | Δ points |",
          "|---|---|---|---|---|---|---|"]
    for r in payload["ablations"]:
        ci = r["recall5_delta_ci95"]
        md.append(f"| {r['removed']} | {100 * r['recall5']:.1f} | {r['recall5_delta_points']:+.1f} "
                  f"[{ci[0]:+.1f}, {ci[1]:+.1f}] | {r['mrr']:.3f} | {r['mrr_delta_points']:+.1f} | "
                  f"{r['ndcg10']:.3f} | {r['ndcg10_delta_points']:+.1f} |")
    (out_dir / f"{stem}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pipeline", default=None)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--personas", nargs="*", default=None)
    ap.add_argument("--results", type=Path, default=rag_eval.REPO / "evals" / "results"
                    / "rag_variants.json")
    ap.add_argument("--dev-dir", type=Path, default=rag_eval.REPO / "evals" / "datasets")
    ap.add_argument("--jobs", type=Path, default=rag_eval.REPO / "data" / "gigsim_seed" / "jobs.jsonl")
    ap.add_argument("--personas-dir", type=Path, default=config.personas_root())
    ap.add_argument("--index-root", type=Path, default=config.index_root())
    ap.add_argument("--out-dir", type=Path, default=rag_eval.REPO / "evals" / "results")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    pipeline = args.pipeline or best_variant(args.results)
    personas = args.personas or [p for p in rag_eval.PERSONAS
                                 if (args.dev_dir / f"dev_{p}.jsonl").exists()]
    run(pipeline, personas=personas, dev_dir=args.dev_dir, jobs_path=args.jobs,
        personas_dir=args.personas_dir, index_root=args.index_root, out_dir=args.out_dir,
        smoke=args.smoke)


if __name__ == "__main__":
    main()
