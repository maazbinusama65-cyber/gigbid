"""Background work (E1): scouting sweeps and long agent runs execute here, never inside web requests.

Idempotency: a job runs on the deterministic thread `bid:<user>:<job>`. A restarted worker finds the
checkpoint, so it resumes (or reports) instead of re-analysing, and the marketplace de-duplicates writes by
idempotency key, so a crash never double-analyses or double-submits.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from agent.nodes.scout import scan_saved_searches
from agent.runtime import GraphRuntime

log = logging.getLogger("gigbid.worker")


class UserRepo(Protocol):
    """What the worker needs from the API's database (implemented by apps.api.real_services)."""

    def active_users(self) -> list[dict]: ...            # {user_id, persona_id, settings, saved_searches}
    def record_run(self, user_id: str, job_id: str, thread_id: str, status: str, summary: dict) -> None: ...
    def mark_scanned(self, user_id: str, ts: float) -> None: ...
    def last_scanned(self, user_id: str) -> float: ...


@dataclass
class SweepResult:
    queued: list[tuple[str, str]] = field(default_factory=list)
    skipped_recent: list[str] = field(default_factory=list)


def min_interval_seconds(runtime: GraphRuntime) -> float:
    """Conservative polling interval: live Upwork is hours apart, the simulator minutes."""
    cfg = runtime.cfg
    if cfg.marketplace_mode == "upwork_live":
        return float(cfg["marketplace"]["live_poll_interval_minutes"]) * 60
    return float(cfg["marketplace"].get("sim_poll_interval_minutes", 15)) * 60


async def scout_sweep(runtime: GraphRuntime, repo: UserRepo, now: float | None = None) -> SweepResult:
    """Run every user's saved searches (respecting the interval + jitter) and return NEW jobs to queue."""
    now = now or time.time()
    interval = min_interval_seconds(runtime)
    res = SweepResult()
    for u in repo.active_users():
        jitter = random.Random(u["user_id"]).uniform(0, 0.1) * interval        # stable per-user jitter
        if now - repo.last_scanned(u["user_id"]) < interval + jitter:
            res.skipped_recent.append(u["user_id"])
            continue
        ctx = runtime.ctx_for(f"scout:{u['user_id']}")
        ids = await scan_saved_searches(ctx, u["user_id"], u.get("saved_searches", []))
        repo.mark_scanned(u["user_id"], now)
        res.queued += [(u["user_id"], j) for j in ids]
    return res


async def run_bid_job(runtime: GraphRuntime, repo: UserRepo, user: dict, job_id: str) -> dict[str, Any]:
    """Analyse one job to its first stop (skip / blocked / awaiting approval). Idempotent."""
    last: dict = {}
    async for ev in runtime.run_bid(user["user_id"], user["persona_id"], job_id, user.get("settings", {})):
        last = ev
    state = last.get("state", {})
    status = "awaiting_approval" if last.get("interrupted") else state.get("status", "unknown")
    repo.record_run(user["user_id"], job_id, runtime.bid_thread_id(user["user_id"], job_id), status,
                    {"usage": last.get("usage"), "decision": state.get("decision"),
                     "last": {k: v for k, v in last.items() if k != "ctx"}})
    return {"job_id": job_id, "status": status}
