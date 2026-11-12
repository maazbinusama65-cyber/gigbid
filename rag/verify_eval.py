"""Measure the claim verifier on labelled adversarial drafts built from the real persona corpora.

    python -m rag.verify_eval            # writes evals/results/rag_verify.json

For each project a draft mixes TRUE claims (taken from the project's fact sheet) with FABRICATED
ones of four kinds: invented client name, invented years of experience, invented metric, invented
tool. Ground truth is known by construction, so we report (against the evidence the retriever
actually returned): detection recall per fabrication kind (fabricated text absent from the repaired
draft), false-flag rate on true claims (true claim removed/changed), and the unsupported-claim
rate before and after repair (same checker; after ~ 0 by construction, so detection recall is the
meaningful number). Seeded; no LLM.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from rag import config
from rag.embedder import get_embedder
from rag.retriever import build_index, get_retriever
from rag.verify import verify_and_repair_detailed

CLIENTS = ["Zorblax Holdings", "Quillfeather Labs", "Nimbus Harbor Ltd", "Ostrava Freight Group",
           "Pelican Ridge Capital", "Tundra Analytics Inc"]
TOOLS = ["Kubernetes", "Rust", "Salesforce", "SAP HANA", "Terraform", "COBOL", "Unity", "Ansible"]
METRIC_FMT = "It improved conversion by {n}% within three weeks."


def build_cases(projects: list[dict], profile_skills: list[str], rng: random.Random,
                n_per_project: int = 1) -> list[dict]:
    own = {s.lower() for s in profile_skills}
    tools = [t for t in TOOLS if t.lower() not in own]
    cases = []
    for proj in projects:
        for _ in range(n_per_project):
            skills = proj["skills"][:2]
            true = [f"I built the {proj['title']} project using {' and '.join(skills)}.",
                    f"Result: {proj['outcome_summary']}."]
            fakes = [
                ("client", f"I delivered {proj['title']} for {rng.choice(CLIENTS)}.",
                 CLIENTS),
                ("years", f"I have {rng.choice([7, 11, 13, 17])} years of experience with "
                          f"{skills[0]}.", None),
                ("metric", METRIC_FMT.format(n=rng.choice([57, 63, 71, 88, 94])), None),
                ("tool", f"I also shipped it on {rng.choice(tools)}.", tools),
            ]
            cases.append({"project_id": proj["project_id"], "title": proj["title"], "true": true,
                          "fakes": fakes})
    return cases


def _fabricated_token(kind: str, text: str, pool: list[str] | None) -> str:
    if kind == "client":
        return next(c for c in pool if c in text)
    if kind == "tool":
        return next(t for t in pool if t in text)
    if kind == "years":
        return text.split(" years")[0].split()[-1] + " years"
    return text.split("by ")[1].split("%")[0] + "%"


def run(personas: list[str] | None = None, per_project: int = 1, seed: int = 0,
        variant: str = "v2_hybrid", out: Path | None = None) -> dict:
    rng = random.Random(seed)
    embedder = get_embedder()
    stats = {k: {"n": 0, "detected": 0} for k in ("client", "years", "metric", "tool")}
    true_n = true_flagged = 0
    unsup_before = unsup_after = claims_before = 0
    ungrounded_before = ungrounded_after = 0
    for persona in personas or ["ai_ml", "fullstack", "data_analyst"]:
        pdir = config.personas_root() / persona
        projects = json.loads((pdir / "projects.json").read_text(encoding="utf-8"))
        profile = json.loads((pdir / "profile.json").read_text(encoding="utf-8"))
        retr = get_retriever(variant, index=build_index(persona, embedder=embedder))
        for case in build_cases(projects, profile["skills"], rng, per_project):
            evidence = retr.search(case["title"], k=5)
            fake_texts = [f[1] for f in case["fakes"]]
            draft = " ".join(case["true"] + fake_texts)
            res = verify_and_repair_detailed(draft, evidence, embedder=embedder)
            claims_before += res.stats["n_claims_before"]
            unsup_before += res.stats["unsupported_before"]
            unsup_after += res.stats["unsupported_after"]
            ungrounded_before += round(res.stats["ungrounded_rate_before"]
                                       * res.stats["n_claims_before"])
            ungrounded_after += round(res.stats["ungrounded_rate_after"]
                                      * res.stats["n_claims_after"])
            for kind, text, pool in case["fakes"]:
                token = _fabricated_token(kind, text, pool)
                stats[kind]["n"] += 1
                stats[kind]["detected"] += token not in res.repaired
            true_n += len(case["true"])
            true_flagged += sum(t.rstrip(".") not in res.repaired for t in case["true"])
    report = {
        "protocol": {"embedder": embedder.name, "retrieval_variant": variant, "seed": seed,
                     "drafts": sum(v["n"] for v in stats.values()) // 4},
        "fabrication_detection": {k: {**v, "recall": v["detected"] / v["n"] if v["n"] else None}
                                  for k, v in stats.items()},
        "true_claims": {"n": true_n, "altered_or_removed": true_flagged,
                        "false_flag_rate": true_flagged / true_n if true_n else None},
        "claim_level": {"n_claims_before": claims_before, "unsupported_before": unsup_before,
                        "unsupported_after": unsup_after,
                        "ungrounded_before": ungrounded_before,
                        "ungrounded_after": ungrounded_after},
    }
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


if __name__ == "__main__":
    out_path = config.REPO_ROOT / "evals" / "results" / "rag_verify.json"
    print(json.dumps(run(out=out_path), indent=1))
