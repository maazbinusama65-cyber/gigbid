"""Scout: fetch a job through the marketplace tool, de-duplicate, hand it to the graph."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from pathlib import Path

from agent.config_loader import ROOT
from agent.nodes.common import Ctx


def unwrap(res, key: str):
    """MCP tools may return the object directly or wrapped under a key."""
    if isinstance(res, dict) and key in res and len(res) <= 3:
        return res[key]
    return res


def fingerprint(job: dict) -> str:
    norm = re.sub(r"[^a-z0-9 ]+", "", f"{job.get('title','')} {job.get('description','')[:400]}".lower())
    norm = re.sub(r"\s+", " ", norm).strip()
    return hashlib.sha1(norm.encode()).hexdigest()


class DedupStore:
    """Per-user seen-job fingerprints (sqlite). Idempotent: a re-run never double-queues a job."""

    def __init__(self, path: Path | str | None = None):
        mem = str(path) == ":memory:"
        p = Path(path) if path and not mem else ROOT / "data" / "processed" / "seen_jobs.sqlite"
        if not mem:
            p.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(":memory:" if mem else str(p), check_same_thread=False)
        self._db.execute("create table if not exists seen (user text, fp text, job_id text, primary key(user, fp))")
        self._lock = threading.Lock()

    def claim(self, user: str, fp: str, job_id: str) -> str:
        """Return the job_id that owns this fingerprint (== job_id if first time)."""
        with self._lock:
            row = self._db.execute("select job_id from seen where user=? and fp=?", (user, fp)).fetchone()
            if row:
                return row[0]
            self._db.execute("insert into seen values (?,?,?)", (user, fp, job_id))
            self._db.commit()
            return job_id


_dedup: DedupStore | None = None


def get_dedup() -> DedupStore:
    global _dedup
    if _dedup is None:
        _dedup = DedupStore()
    return _dedup


def set_dedup_store(store: DedupStore) -> None:
    global _dedup
    _dedup = store


async def scout(state: dict, ctx: Ctx) -> dict:
    job_id = state["job_id"]
    job = state.get("job")
    if not job:
        job = unwrap(await ctx.call("scout", "get_job", {"job_id": job_id}), "job")
    owner = get_dedup().claim(state.get("user_id", "anon"), fingerprint(job), job_id)
    if owner != job_id and not state.get("settings", {}).get("force_bid"):
        return {"job": job, "status": "skipped", "status_reason": f"duplicate of {owner}",
                "decision": {"decision": "skip", "reasons": [f"duplicate of {owner}"], "auto_skipped": True}}
    return {"job": job, "status": "running"}


async def scan_saved_searches(ctx: Ctx, user_id: str, searches: list[dict], limit: int = 25) -> list[str]:
    """Worker entry: run saved searches, de-duplicate, return NEW job ids to queue."""
    new: list[str] = []
    seen_ids: set[str] = set()
    for s in searches:
        res = await ctx.call("scout", "search_jobs", {"query": s.get("query", ""), "category": s.get("category"),
                                                      "limit": limit})
        jobs = res.get("jobs", res) if isinstance(res, dict) else res
        for j in jobs:
            if j["job_id"] in seen_ids:
                continue
            seen_ids.add(j["job_id"])
            if get_dedup().claim(user_id, fingerprint(j), j["job_id"]) == j["job_id"]:
                new.append(j["job_id"])
    return new
