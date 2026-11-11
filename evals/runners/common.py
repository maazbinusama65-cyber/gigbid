"""Shared helpers for eval runners: dataset loading, results writing."""
from __future__ import annotations

import json
from pathlib import Path

from agent.config_loader import ROOT

RESULTS = ROOT / "evals" / "results"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")


def dev_jobs(persona: str) -> list[dict]:
    p = ROOT / "evals" / "datasets" / f"dev_{persona}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def seed_jobs() -> dict[str, dict]:
    p = ROOT / "data" / "gigsim_seed" / "jobs.jsonl"
    return {j["job_id"]: j for j in (json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip())}


def write_result(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / name
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p
