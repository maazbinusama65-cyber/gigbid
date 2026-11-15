"""LLM-judge calibration harness (B4: "label 30 items yourself and report Cohen's kappa").

    python -m evals.runners.judge_calibration sample            # write the 30 items to label
    python -m evals.runners.judge_calibration label             # tiny interactive labelling CLI
    python -m evals.runners.judge_calibration judge --provider groq   # LLM-judge scores (optional)
    python -m evals.runners.judge_calibration report            # kappa, or 'awaiting human labels'

Files (evals/results/):
    judge_calibration_items.json   30 items sampled for hand labelling (seeded, stratified)
    judge_calibration_labels.json  YOUR labels: {"labels": {"<item_id>": 1..5}} (never invented here)
    judge_calibration_judge.json   judge scores, same shape (written by `judge`)
    judge_calibration_report.json  agreement report

Rubric (1-5): 5 = specific, true to the portfolio, answers the client's need, no filler;
3 = relevant but generic or partly unsupported; 1 = generic boilerplate, off-topic or fabricated.
Binary view for kappa: good = score >= 4. This script NEVER fabricates labels or kappa: with no
labels file it reports `awaiting human labels`; with labels but no judge scores it reports
`awaiting judge scores`.

Items are past proposals from data/personas/*/proposals.json (stratified by persona and outcome).
Use `sample --source drafts.jsonl` (lines of {"item_id", "persona", "job_title", "text"}) to
calibrate on agent drafts instead.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from rag import config

RESULTS = config.REPO_ROOT / "evals" / "results"
ITEMS = RESULTS / "judge_calibration_items.json"
LABELS = RESULTS / "judge_calibration_labels.json"
JUDGE = RESULTS / "judge_calibration_judge.json"
REPORT = RESULTS / "judge_calibration_report.json"
N_ITEMS = 30
RUBRIC = ("Score the proposal 1-5. 5: specific, concrete evidence, no filler, answers the "
          "client's need. 3: relevant but generic or partly unsupported. 1: boilerplate, "
          "off-topic or fabricated. Reply with JSON {\"score\": <1-5>, \"reason\": \"...\"}.")


# ----------------------------------------------------------------------------- statistics
def cohens_kappa(a: list[int], b: list[int], weights: str | None = None,
                 categories: list[int] | None = None) -> float:
    """Cohen's kappa for two raters. weights: None | 'linear' | 'quadratic'."""
    if len(a) != len(b) or not a:
        raise ValueError("rating lists must be non-empty and equal length")
    cats = categories or sorted(set(a) | set(b))
    k, n = len(cats), len(a)
    idx = {c: i for i, c in enumerate(cats)}
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        obs[idx[x]][idx[y]] += 1.0 / n
    ra = [sum(row) for row in obs]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]

    def w(i: int, j: int) -> float:
        if weights is None:
            return 0.0 if i == j else 1.0
        d = abs(i - j) / (k - 1) if k > 1 else 0.0
        return d if weights == "linear" else d * d

    num = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w(i, j) * ra[i] * rb[j] for i in range(k) for j in range(k))
    if den == 0:
        return 1.0 if num == 0 else 0.0
    return 1.0 - num / den


# ----------------------------------------------------------------------------- sampling
def sample_items(personas_dir: Path, n: int = N_ITEMS, seed: int = 0,
                 source: Path | None = None) -> list[dict]:
    rng = random.Random(seed)
    if source:
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        rng.shuffle(rows)
        return rows[:n]
    pool: dict[tuple[str, str], list[dict]] = {}
    for pdir in sorted(p for p in personas_dir.iterdir() if p.is_dir()):
        path = pdir / "proposals.json"
        if not path.exists():
            continue
        for prop in json.loads(path.read_text(encoding="utf-8")):
            pool.setdefault((pdir.name, prop["outcome"]), []).append(
                {"item_id": prop["proposal_id"], "persona": pdir.name,
                 "job_title": prop["job_title"], "text": prop["text"],
                 "outcome_hidden_from_labeller": prop["outcome"]})
    strata = sorted(pool)
    for s in strata:
        rng.shuffle(pool[s])
    picked: list[dict] = []
    while len(picked) < n and any(pool[s] for s in strata):  # round-robin over strata
        for s in strata:
            if pool[s] and len(picked) < n:
                picked.append(pool[s].pop())
    rng.shuffle(picked)
    return picked


def write_items(items: list[dict], path: Path = ITEMS) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    visible = [{k: v for k, v in it.items() if k != "outcome_hidden_from_labeller"} for it in items]
    meta = Counter(it.get("outcome_hidden_from_labeller", "n/a") for it in items)
    path.write_text(json.dumps({"rubric": RUBRIC, "n": len(items), "strata_outcomes": dict(meta),
                                "items": visible}, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------- labels / judge
def load_scores(path: Path) -> dict[str, int] | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    labels = raw.get("labels", raw) if isinstance(raw, dict) else {}
    return {k: int(v) for k, v in labels.items() if str(v).strip() != ""}


def label_cli(items_path: Path = ITEMS, labels_path: Path = LABELS, inp=input, out=print) -> None:
    items = json.loads(items_path.read_text(encoding="utf-8"))["items"]
    labels = load_scores(labels_path) or {}
    out(f"Rubric: {RUBRIC}\nEnter 1-5, s to skip, q to quit. {len(labels)}/{len(items)} labelled.")
    for it in items:
        if it["item_id"] in labels:
            continue
        out(f"\n--- {it['item_id']} ({it['persona']}) job: {it['job_title']}\n{it['text']}\n")
        while True:
            ans = inp("score [1-5/s/q]> ").strip().lower()
            if ans in ("q", "s") or ans in {"1", "2", "3", "4", "5"}:
                break
        if ans == "q":
            break
        if ans != "s":
            labels[it["item_id"]] = int(ans)
            labels_path.write_text(json.dumps({"labels": labels}, indent=1), encoding="utf-8")
    out(f"saved {len(labels)}/{len(items)} labels to {labels_path}")


def groq_judge(text: str, job_title: str) -> int:  # pragma: no cover - needs network + key
    """Judge via an OpenAI-compatible endpoint; model/base_url come from agent/config.yaml."""
    import httpx

    import agent.config_loader  # noqa: F401  - side effect: loads the git-ignored .env (GROQ_API_KEY)

    prof = config.load_config()["models"]["profiles"]["open"]
    model = prof["nodes"]["judge"]["model"]
    key = os.environ[prof["api_key_env"]]
    for attempt in range(8):            # free-tier rate limits: honour Retry-After, back off, then fail loudly
        resp = httpx.post(f"{prof['base_url']}/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "temperature": 0,
                                "messages": [{"role": "system", "content": RUBRIC},
                                             {"role": "user", "content":
                                              f"Job: {job_title}\n\nProposal:\n{text}"}]})
        if resp.status_code != 429:
            break
        time.sleep(min(90.0, float(resp.headers.get("retry-after", 2 ** attempt * 3))))
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return int(json.loads(content[content.index("{"): content.rindex("}") + 1])["score"])


def run_judge(items: list[dict], judge_fn, path: Path = JUDGE) -> dict[str, int]:
    scores = {it["item_id"]: int(judge_fn(it["text"], it["job_title"])) for it in items}
    path.write_text(json.dumps({"labels": scores}, indent=1), encoding="utf-8")
    return scores


# ----------------------------------------------------------------------------- report
def build_report(labels: dict[str, int] | None, judge: dict[str, int] | None) -> dict[str, Any]:
    if not labels:
        return {"status": "awaiting human labels", "n_labelled": 0,
                "how": "python -m evals.runners.judge_calibration label"}
    if not judge:
        return {"status": "awaiting judge scores", "n_labelled": len(labels),
                "how": "python -m evals.runners.judge_calibration judge --provider groq"}
    ids = sorted(set(labels) & set(judge))
    if len(ids) < 2:
        return {"status": "no overlapping items", "n_labelled": len(labels)}
    h, j = [labels[i] for i in ids], [judge[i] for i in ids]
    hb, jb = [int(x >= 4) for x in h], [int(x >= 4) for x in j]
    report = {"status": "ok", "n": len(ids),
              "kappa_binary_good_ge4": cohens_kappa(hb, jb, categories=[0, 1]),
              "kappa_ordinal_quadratic": cohens_kappa(h, j, "quadratic", [1, 2, 3, 4, 5]),
              "kappa_ordinal_unweighted": cohens_kappa(h, j, None, [1, 2, 3, 4, 5]),
              "exact_agreement": sum(x == y for x, y in zip(h, j, strict=True)) / len(ids),
              "mean_human": sum(h) / len(h), "mean_judge": sum(j) / len(j)}
    if len(ids) < N_ITEMS:
        report["warning"] = f"only {len(ids)} of {N_ITEMS} items labelled by both"
    return report


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("command", choices=["sample", "label", "judge", "report"])
    ap.add_argument("--personas-dir", type=Path, default=config.personas_root())
    ap.add_argument("--source", type=Path, default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--provider", choices=["groq"], default="groq")
    args = ap.parse_args(argv)
    if args.command == "sample":
        items = sample_items(args.personas_dir, N_ITEMS, args.seed, args.source)
        write_items(items)
        print(f"wrote {len(items)} items to {ITEMS}; label them with the `label` command")
    elif args.command == "label":
        label_cli()
    elif args.command == "judge":
        items = json.loads(ITEMS.read_text(encoding="utf-8"))["items"]
        scores = run_judge(items, groq_judge)
        print(f"judge scored {len(scores)} items -> {JUDGE}")
    else:
        report = build_report(load_scores(LABELS), load_scores(JUDGE))
        REPORT.write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(json.dumps(report, indent=1))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
