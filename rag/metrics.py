"""Project-level retrieval metrics (gold = set of project ids per job).

A retrieved evidence item credits the project(s) it belongs to: its ``project_id`` (a past
proposal credits every project it cites, ``proposal_credit="all"``; ``"first"`` or ``"none"`` are
sensitivity options). The ranked *project* list is the order of first appearance. Items that
belong to no project (the CV, generic proposals) do not occupy a project rank.
"""
from __future__ import annotations

import math
import random
from collections.abc import Iterable


def ranked_projects(items: Iterable[dict], proposal_credit: str = "all") -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        if it.get("type") == "proposal":
            if proposal_credit == "none":
                continue
            pids = list(it.get("project_ids") or ([it["project_id"]] if it.get("project_id") else []))
            if proposal_credit == "first":
                pids = pids[:1]
        else:
            pids = [it["project_id"]] if it.get("project_id") else []
        for p in pids:
            seen.setdefault(p, None)
    return list(seen)


def recall_at_k(ranked: list[str], gold: set[str], k: int = 5) -> float:
    """Standard recall: |gold hits in top-k| / |gold|."""
    return len(gold & set(ranked[:k])) / len(gold) if gold else 0.0


def capped_recall_at_k(ranked: list[str], gold: set[str], k: int = 5) -> float:
    """Recall normalised by the best achievable at k: hits / min(|gold|, k)."""
    return len(gold & set(ranked[:k])) / min(len(gold), k) if gold else 0.0


def mrr(ranked: list[str], gold: set[str]) -> float:
    for i, p in enumerate(ranked, 1):
        if p in gold:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: list[str], gold: set[str], k: int = 10) -> float:
    if not gold:
        return 0.0
    dcg = sum(1.0 / math.log2(i + 2) for i, p in enumerate(ranked[:k]) if p in gold)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal


def job_metrics(items: list[dict], gold: set[str], proposal_credit: str = "all") -> dict[str, float]:
    ranked = ranked_projects(items, proposal_credit)
    return {"recall5": recall_at_k(ranked, gold, 5),
            "recall5_capped": capped_recall_at_k(ranked, gold, 5),
            "mrr": mrr(ranked, gold), "ndcg10": ndcg_at_k(ranked, gold, 10),
            "ranked": ranked[:10]}


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def percentile(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def paired_bootstrap(diffs: list[float], n_boot: int = 2000, seed: int = 0
                     ) -> tuple[float, float, float]:
    """Mean paired difference and its 95% bootstrap CI (seeded, reproducible)."""
    if not diffs:
        return float("nan"), float("nan"), float("nan")
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return mean(diffs), means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]
