"""Shared helpers for eval runners: dataset loading, results writing."""
from __future__ import annotations

import json
from pathlib import Path

from agent.config_loader import ROOT

RESULTS = ROOT / "evals" / "results"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")


def dev_jobs(persona: str, split: str = "dev") -> list[dict]:
    """Gold labels for a split. `dev` is committed and was used while tuning; `test` is the held-out local set
    (data/processed/local_test_*.jsonl, git-ignored) that was never looked at while tuning."""
    p = (ROOT / "evals" / "datasets" / f"dev_{persona}.jsonl" if split == "dev"
         else ROOT / "data" / "processed" / f"local_{split}_{persona}.jsonl")
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def seed_jobs() -> dict[str, dict]:
    p = ROOT / "data" / "gigsim_seed" / "jobs.jsonl"
    return {j["job_id"]: j for j in (json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip())}


def write_result(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p
