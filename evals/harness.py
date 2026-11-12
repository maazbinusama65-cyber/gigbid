"""Evaluation / demo harness: a real GigSim process + in-process MCP servers + the LangGraph runtime.

The graph talks to GigSim only through the Marketplace MCP server (same code path as production);
the tool transport is `memory` so evals do not need three extra processes.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import httpx

from agent.config_loader import ROOT, Config, load_config
from agent.llm import LLM
from agent.memory.store import LongTermMemory
from agent.runtime import GraphRuntime
from agent.tools import ToolGateway

TOKEN = "eval-gigsim-token"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class EvalEnv:
    runtime: GraphRuntime
    gateway: ToolGateway
    gigsim_url: str
    cfg: Config
    cold_start_s: float = 0.0

    def headers(self, persona_id: str) -> dict:
        return {"Authorization": f"Bearer {TOKEN}", "X-Freelancer-Id": persona_id}


@contextlib.asynccontextmanager
async def eval_env(profile: str = "stub", persona_id: str = "ai_ml", tmp: Path | None = None,
                   overrides: dict | None = None, gigsim_env: dict | None = None,
                   rag_variant: str | None = None) -> AsyncIterator[EvalEnv]:
    tmp = tmp or (ROOT / "data" / "processed" / "eval_tmp")
    tmp.mkdir(parents=True, exist_ok=True)
    port = _free_port()
    env = {**os.environ, "GIGSIM_API_TOKEN": TOKEN, "GIGSIM_PORT": str(port),
           "GIGSIM_STATE_PATH": str(tmp / f"gigsim_{port}.json"), "PYTHONUNBUFFERED": "1", "GIGSIM_RATE_LIMIT_RPM": "100000",
           **(gigsim_env or {})}
    proc = subprocess.Popen([sys.executable, "-m", "gigsim"], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    try:
        async with httpx.AsyncClient() as c:
            for _ in range(100):
                try:
                    if (await c.get(url + "/health")).status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                await asyncio.sleep(0.2)
            else:
                raise RuntimeError("GigSim did not start")
        os.environ.update({"GIGSIM_BASE_URL": url, "GIGSIM_API_TOKEN": TOKEN, "PORTFOLIO_ID": persona_id,
                           "MARKETPLACE_MODE": "gigsim", "MARKETPLACE_DEFAULT_USER": persona_id,
                           "MARKETPLACE_STATE_DIR": str(tmp / f"mcp_state_{port}")})
        os.environ.setdefault("HF_HUB_OFFLINE", "1")        # models are cached; no per-load network round trips
        if rag_variant:
            os.environ["RAG_VARIANT"] = rag_variant
        # evals run flat out against the local simulator; production keeps the polite per-user limit
        all_over = {"models.profile": profile, "marketplace.max_requests_per_minute": 3000, **(overrides or {})}
        cfg = load_config(overrides=all_over)
        import yaml

        cfg_path = tmp / f"config_{port}.yaml"            # the MCP servers read the same config file
        cfg_path.write_text(yaml.safe_dump(dict(cfg)), encoding="utf-8")
        os.environ["GIGBID_CONFIG"] = str(cfg_path)
        from agent.nodes import scout as scout_mod

        scout_mod.set_dedup_store(scout_mod.DedupStore(tmp / f"seen_{port}.sqlite"))   # each eval starts unseen
        gateway = ToolGateway(cfg, user_id=persona_id, transport="memory")
        rt = GraphRuntime(cfg, gateway, llm=LLM(cfg), memory=LongTermMemory(cfg=cfg))
        t0 = time.monotonic()                      # cold start (torch import, index + model load) is paid once
        await gateway.call("fit_matcher", "search_evidence", {"requirement": "warm up", "k": 1, "portfolio_id": persona_id})
        env_ = EvalEnv(rt, gateway, url, cfg)
        env_.cold_start_s = round(time.monotonic() - t0, 2)
        yield env_
    finally:
        proc.terminate()
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)


async def run_job(env: EvalEnv, persona_id: str, job_id: str, settings: dict | None = None,
                  user_id: str | None = None) -> dict:
    """Run one job to its first stop. Returns the last event ('done') with timing."""
    t0 = time.monotonic()
    last: dict = {}
    async for ev in env.runtime.run_bid(user_id or f"eval-{persona_id}", persona_id, job_id, settings or {}):
        last = ev
    last["latency_s"] = time.monotonic() - t0
    return last


def load_profile(persona_id: str) -> dict:
    import json

    return json.loads((ROOT / "data" / "personas" / persona_id / "profile.json").read_text(encoding="utf-8"))
