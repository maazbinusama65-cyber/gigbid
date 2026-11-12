"""CI gate: fail if the 30-job smoke eval regresses past the thresholds in evals/thresholds.json.

    python -m evals.runners.check_thresholds [--results evals/results/decision_stub_smoke.json]
"""
from __future__ import annotations

import argparse
import json
import sys

from agent.config_loader import ROOT


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(ROOT / "evals" / "results" / "decision_stub_smoke.json"))
    ap.add_argument("--thresholds", default=str(ROOT / "evals" / "thresholds.json"))
    a = ap.parse_args()
    res = json.loads(open(a.results, encoding="utf-8").read())["per_persona"]
    th = json.loads(open(a.thresholds, encoding="utf-8").read())
    n = len(res)
    f1 = sum(r["bid_or_skip"]["f1"] for r in res.values()) / n
    scam_recall = sum(r["scam_detection"]["recall"] for r in res.values()) / n
    unsup = sum(r["unsupported_claims_per_proposal"]["after_verification"] or 0 for r in res.values()) / n
    inj = [r["injection"]["rate"] for r in res.values() if r["injection"]["rate"] is not None]
    asr = max(inj) if inj else 0.0
    errors = sum(r["n_errors"] for r in res.values())
    checks = [
        ("bid-or-skip F1 (mean over personas)", f1, f">= {th['min_bid_f1']}", f1 >= th["min_bid_f1"]),
        ("scam recall", scam_recall, f">= {th['min_scam_recall']}", scam_recall >= th["min_scam_recall"]),
        ("unsupported claims per proposal after verification", unsup, f"<= {th['max_unsupported_claims_per_proposal']}",
         unsup <= th["max_unsupported_claims_per_proposal"]),
        ("injection attack success rate", asr, f"<= {th['max_injection_asr']}", asr <= th["max_injection_asr"]),
        ("graph errors", errors, "== 0", errors == 0),
    ]
    bad = False
    for name, val, rule, ok in checks:
        print(f"[{'ok' if ok else 'FAIL'}] {name}: {val:.4f} (need {rule})")
        bad |= not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
