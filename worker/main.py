"""Arq worker (Redis). `arq worker.main.WorkerSettings`.

Wiring to the API database and the tool gateway is in `build_runtime()` / `repo` so the same task code
runs inline in tests (see tests/unit/test_worker.py) and under Arq in production.
"""
from __future__ import annotations

import os
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from agent.config_loader import load_config
from worker.tasks import run_bid_job, scout_sweep


async def startup(ctx: dict[str, Any]) -> None:
    from apps.api.real_services import build_runtime, build_user_repo  # lazy: heavy imports

    ctx["runtime"] = await build_runtime(load_config())
    ctx["repo"] = build_user_repo()


async def shutdown(ctx: dict[str, Any]) -> None:
    rt = ctx.get("runtime")
    if rt:
        await rt.llm.aclose()


async def sweep(ctx: dict[str, Any]) -> dict:
    res = await scout_sweep(ctx["runtime"], ctx["repo"])
    for user_id, job_id in res.queued:                      # fan out: one Arq job per new job
        await ctx["redis"].enqueue_job("analyse_job", user_id, job_id, _job_id=f"bid:{user_id}:{job_id}")
    return {"queued": len(res.queued), "skipped_recent": len(res.skipped_recent)}


async def analyse_job(ctx: dict[str, Any], user_id: str, job_id: str) -> dict:
    user = next((u for u in ctx["repo"].active_users() if u["user_id"] == user_id), None)
    if not user:
        return {"error": "unknown user"}
    return await run_bid_job(ctx["runtime"], ctx["repo"], user, job_id)


class WorkerSettings:
    functions = [sweep, analyse_job]
    cron_jobs = [cron(sweep, minute={0, 15, 30, 45}, run_at_startup=False)]   # interval gate is in scout_sweep
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    max_jobs = 4
    job_timeout = 300
    max_tries = 3            # retried tasks are safe: threads and writes are idempotent
    keep_result = 3600
