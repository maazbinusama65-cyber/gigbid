"""Clean retrieval-latency measurement for the variants that matter (run on an otherwise idle machine).

    python -m evals.runners.rag_latency

The latency stored in rag_variants.json was measured in sequence while other jobs were using the CPU, so it is
order- and load-dependent. This runner warms the models once, then measures each variant twice in interleaved
order (cold query caches before every job, as in rag_eval.measure_latency) and keeps the faster pass, which
removes most one-off contention. Writes evals/results/rag_latency.json.
"""
from __future__ import annotations

import json
import logging
import platform
import random
from datetime import UTC, datetime
from pathlib import Path

from evals.runners.common import write_result
from evals.runners.rag_eval import PERSONAS, REPO, load_eval_data, measure_latency
from rag import config
from rag.embedder import get_embedder
from rag.retriever import build_index

VARIANTS = ["v0_naive", "v2_hybrid", "v3_rerank", "v9_skill_graph", "v1_decompose+v2_hybrid",
            "v1_decompose+v2_hybrid+v3_rerank+v9_skill_graph"]
PASSES = 2


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    random.seed(0)
    dev_dir, jobs = REPO / "evals" / "datasets", REPO / "data" / "gigsim_seed" / "jobs.jsonl"
    embedder = get_embedder()
    data = {p: load_eval_data(p, dev_dir, jobs) for p in PERSONAS}
    indexes = {p: build_index(p, embedder=embedder, personas_dir=config.personas_root(),
                              index_root=config.index_root()) for p in PERSONAS}
    for v in VARIANTS[:2]:                                   # warm-up pass, discarded
        measure_latency(v, {p: rows[:2] for p, rows in data.items()}, indexes)
    best: dict[str, dict] = {}
    for n in range(PASSES):
        for v in VARIANTS:
            m = measure_latency(v, data, indexes)
            logging.info("pass %d %-50s p50 %.0f ms p95 %.0f ms", n + 1, v, m["p50_ms"], m["p95_ms"])
            if v not in best or m["p50_ms"] < best[v]["p50_ms"]:
                best[v] = m
    out = {"protocol": {"passes": PASSES, "kept": "faster pass by p50", "unit": "ms per job (all requirements), query caches cleared",
                        "embedder": embedder.name, "python": platform.python_version(),
                        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                        "note": "measure on an idle machine; compare with latency_cold in rag_variants.json, which was measured under load"},
           "variants": best}
    print(json.dumps({v: {k: round(x) for k, x in m.items() if k != "n"} for v, m in best.items()}, indent=1))
    print("wrote", write_result("rag_latency.json", out))
    _ = Path


if __name__ == "__main__":
    main()
