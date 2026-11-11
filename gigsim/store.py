"""Seed data (jobs, clients, stats) and persisted simulator state."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from .catalog_projects import PERSONA_IDS
from .catalog_skills import CATEGORIES
from .jobgen import CLOCK_START

JOB_FIELDS = ["job_id", "client_id", "title", "description", "category", "required_skills", "budget",
              "duration_days", "screening_questions", "posted_at", "connects_cost"]
CLIENT_FIELDS = ["client_id", "name", "industry", "payment_verified", "total_spent", "hire_rate", "avg_rating",
                 "jobs_posted", "member_since", "country", "history"]
START_TS = int(CLOCK_START.timestamp())


def iso_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


class SeedData:
    def __init__(self, seed_dir: Path, extra_jobs: str | None = None):
        rows = _jsonl(seed_dir / "jobs.jsonl")
        if extra_jobs:  # e.g. data/processed/local_test_<persona>.jsonl rows ({..., "job": {...}}) or bare jobs
            for r in _jsonl(Path(extra_jobs)):
                j = dict(r.get("job", r))
                j.setdefault("kind", "dev")
                rows.append(j)
        self.jobs = {r["job_id"]: r for r in rows}
        self.clients = {c["client_id"]: c for c in _jsonl(seed_dir / "clients.jsonl")}
        sp = seed_dir / "history_stats.json"
        self.stats = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
        self.stats_lc = {k.lower(): k for k in self.stats}
        self.open_jobs = sorted((r for r in rows if r.get("kind") in ("stream", "dev")),
                                key=lambda r: (r["posted_at"], r["job_id"]), reverse=True)

    @staticmethod
    def public_job(j: dict) -> dict:
        out = {k: j.get(k) for k in JOB_FIELDS}
        if j.get("kind") == "history":
            out["final_price"] = j.get("final_price")
        return out

    def public_client(self, c: dict) -> dict:
        return {k: c.get(k) for k in CLIENT_FIELDS}

    def category_key(self, name: str) -> str | None:
        n = name.strip().lower()
        if n in CATEGORIES:
            n = CATEGORIES[n].lower()
        return self.stats_lc.get(n)


def fresh_state(seed: int, initial_balance: int) -> dict:
    return {"seed": seed, "clock": START_TS, "week": 0,
            "counters": {"proposal": 0, "message": 0, "event": 0, "thread": 0},
            "freelancers": {f: {"balance": initial_balance, "spent_this_week": 0} for f in PERSONA_IDS},
            "proposals": {}, "threads": {}, "messages": [], "events": [], "idempotency": {}}


class StateStore:
    """JSON-file persistence (atomic replace). path '' keeps state in memory only."""

    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict | None:
        if not self.path or not os.path.exists(self.path):
            return None
        try:
            return json.loads(Path(self.path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, state: dict) -> None:
        if not self.path:
            return
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, p)
