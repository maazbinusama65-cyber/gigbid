"""Pure metric functions used by every eval runner (no I/O, fully unit-tested)."""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4), "tp": tp, "fp": fp, "fn": fn}


def binary_prf(gold: Sequence[bool], pred: Sequence[bool]) -> dict[str, float]:
    tp = sum(g and p for g, p in zip(gold, pred, strict=True))
    fp = sum((not g) and p for g, p in zip(gold, pred, strict=True))
    fn = sum(g and (not p) for g, p in zip(gold, pred, strict=True))
    return prf(tp, fp, fn)


def recall_at_k(ranked: Sequence[str], gold: set[str], k: int) -> float:
    if not gold:
        return float("nan")
    return len(set(ranked[:k]) & gold) / len(gold)


def mrr(ranked: Sequence[str], gold: set[str]) -> float:
    if not gold:
        return float("nan")
    for i, r in enumerate(ranked, 1):
        if r in gold:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], gold: set[str], k: int = 10) -> float:
    if not gold:
        return float("nan")
    dcg = sum(1.0 / math.log2(i + 2) for i, r in enumerate(ranked[:k]) if r in gold)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def mean(xs: Iterable[float]) -> float:
    v = [x for x in xs if x == x]  # drops NaN
    return round(sum(v) / len(v), 4) if v else float("nan")


def percentile(xs: Sequence[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 4)


def in_band(price: float, band: dict) -> bool:
    return band["min"] <= price <= band["max"]


def cohens_kappa(a: Sequence[int], b: Sequence[int]) -> float:
    """Cohen's kappa for two raters over the same items (labels may be any hashable)."""
    n = len(a)
    if n == 0 or n != len(b):
        return float("nan")
    labels = sorted(set(a) | set(b))
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    pe = sum((a.count(lab) / n) * (b.count(lab) / n) for lab in labels)
    return round((po - pe) / (1 - pe), 4) if pe < 1 else 1.0


def two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> dict[str, float]:
    """Two-sided z-test for a difference in reply rates (used for A/B proposal experiments)."""
    if min(n1, n2) == 0:
        return {"z": float("nan"), "p": float("nan")}
    p1, p2, p = x1 / n1, x2 / n2, (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return {"z": 0.0, "p": 1.0, "p1": p1, "p2": p2}
    z = (p1 - p2) / se
    pval = math.erfc(abs(z) / math.sqrt(2))
    return {"z": round(z, 4), "p": round(pval, 6), "p1": round(p1, 4), "p2": round(p2, 4)}


def wilson(x: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = x / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round((c - m) / d, 4), round((c + m) / d, 4))
