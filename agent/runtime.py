"""Graph runtime: builds the context, the durable checkpointer, and run / stream / resume / replay helpers.

Checkpointer: Postgres when DATABASE_URL is postgres (docker compose, deploy), otherwise a sqlite file
(local dev). Both survive a process crash; tests may use the in-memory saver.
"""
from __future__ import annotations

import logging
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent.config_loader import ROOT, Config, load_config
from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.llm import LLM, UsageTracker
from agent.memory.store import LongTermMemory, make_store
from agent.nodes.common import Ctx
from agent.policy import Policy
from agent.trace import TraceRecorder, new_trace_id, set_trace_id

log = logging.getLogger("gigbid.runtime")


async def make_checkpointer(url: str | None = None) -> BaseCheckpointSaver:
    url = url or os.getenv("DATABASE_URL", "")
    if url.startswith("postgres"):
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row

        conn_url = url.replace("postgresql+psycopg://", "postgresql://")
        conn = await AsyncConnection.connect(conn_url, autocommit=True, prepare_threshold=0, row_factory=dict_row)
        saver = AsyncPostgresSaver(conn)
        await saver.setup()
        return saver
    if url == "memory":
        return InMemorySaver()
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    path = Path(os.getenv("CHECKPOINT_DB", ROOT / "data" / "processed" / "checkpoints.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(str(path))
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver


class GraphRuntime:
    def __init__(self, cfg: Config, tools: Any, llm: LLM | None = None, memory: LongTermMemory | None = None,
                 checkpointer: BaseCheckpointSaver | None = None, policy: Policy | None = None):
        self.cfg = cfg
        self.tools = tools
        self.llm = llm or LLM(cfg)
        self.memory = memory or LongTermMemory(make_store(os.getenv("MEMORY_DB")) if os.getenv("MEMORY_DB") else None, cfg)
        self.policy = policy or Policy()
        self.checkpointer = checkpointer or InMemorySaver()

    # one Ctx per run so tracker / recorder are per-run
    def ctx_for(self, run_id: str) -> Ctx:
        return Ctx(cfg=self.cfg, llm=self.llm, tools=self.tools, memory=self.memory, policy=self.policy,
                   recorder=TraceRecorder(run_id), tracker=UsageTracker())

    def bid_graph(self, ctx: Ctx):
        return build_bid_graph(ctx, self.checkpointer)

    def conv_graph(self, ctx: Ctx):
        return build_conversation_graph(ctx, self.checkpointer)

    @staticmethod
    def bid_thread_id(user_id: str, job_id: str) -> str:
        return f"bid:{user_id}:{job_id}"

    @staticmethod
    def conv_thread_id(user_id: str, marketplace_thread_id: str) -> str:
        return f"conv:{user_id}:{marketplace_thread_id}"

    async def run_bid(self, user_id: str, persona_id: str, job_id: str, settings: dict | None = None,
                      thread_id: str | None = None, trace_id: str | None = None) -> AsyncIterator[dict]:
        """Start (or idempotently continue) the bid graph for one job. Yields stream events."""
        thread_id = thread_id or self.bid_thread_id(user_id, job_id)
        ctx = self.ctx_for(thread_id)
        graph = self.bid_graph(ctx)
        config = {"configurable": {"thread_id": thread_id}}
        existing = await graph.aget_state(config)
        set_trace_id(trace_id or new_trace_id())
        if existing and existing.values and (existing.next or existing.values.get("status")):
            # a restarted worker must never re-analyse: resume only if it is waiting, else report as is
            ctx._trace("idempotent_skip", None, thread_id=thread_id, status=existing.values.get("status"))
            yield {"type": "done", "state": existing.values, "interrupted": bool(existing.next), "ctx": ctx}
            return
        init = {"thread_id": thread_id, "run_id": thread_id, "user_id": user_id, "persona_id": persona_id,
                "job_id": job_id, "settings": settings or {}, "status": "running", "revision": 0}
        async for ev in self._drive(graph, ctx, init, config):
            yield ev

    async def resume(self, thread_id: str, decision: dict, kind: str = "bid") -> AsyncIterator[dict]:
        ctx = self.ctx_for(thread_id)
        graph = self.bid_graph(ctx) if kind == "bid" else self.conv_graph(ctx)
        config = {"configurable": {"thread_id": thread_id}}
        ctx._trace("resume", None, action=decision.get("action"))
        async for ev in self._drive(graph, ctx, Command(resume=decision), config):
            yield ev

    async def run_conversation(self, user_id: str, persona_id: str, marketplace_thread_id: str, job_id: str | None,
                               settings: dict | None = None) -> AsyncIterator[dict]:
        thread_id = self.conv_thread_id(user_id, marketplace_thread_id)
        ctx = self.ctx_for(thread_id)
        graph = self.conv_graph(ctx)
        config = {"configurable": {"thread_id": thread_id}}
        init = {"thread_id": thread_id, "run_id": thread_id, "user_id": user_id, "persona_id": persona_id,
                "marketplace_thread_id": marketplace_thread_id, "job_id": job_id or "", "settings": settings or {},
                "status": "running"}
        async for ev in self._drive(graph, ctx, init, config):
            yield ev

    async def _drive(self, graph, ctx: Ctx, input_: Any, config: dict) -> AsyncIterator[dict]:
        interrupted: dict | None = None
        try:
            async for chunk in graph.astream(input_, config, stream_mode="updates"):
                for node, upd in chunk.items():
                    if node == "__interrupt__":
                        interrupted = upd[0].value if upd else {}
                        ctx._trace("interrupt", "approval", kind=(interrupted or {}).get("kind"))
                        yield {"type": "interrupt", "node": "approval", "data": interrupted}
                    else:
                        yield {"type": "node_end", "node": node, "data": {k: v for k, v in (upd or {}).items() if k in ("status", "decision", "price_quote", "claim_stats")}}
        except Exception as e:  # noqa: BLE001
            ctx._trace("run_error", None, error=str(e)[:300])
            yield {"type": "error", "data": {"error": str(e)[:300]}}
            return
        snap = await graph.aget_state(config)
        yield {"type": "done", "state": snap.values, "interrupted": bool(snap.next), "pending": interrupted,
               "usage": ctx.tracker.snapshot(), "ctx": ctx}

    async def state(self, thread_id: str, kind: str = "bid") -> dict | None:
        ctx = self.ctx_for(thread_id)
        graph = self.bid_graph(ctx) if kind == "bid" else self.conv_graph(ctx)
        snap = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        if not snap or not snap.values:
            return None
        pending = [i.value for t in snap.tasks for i in getattr(t, "interrupts", [])]
        return {"values": snap.values, "next": list(snap.next), "pending": pending}

    async def history(self, thread_id: str, kind: str = "bid") -> list[dict]:
        ctx = self.ctx_for(thread_id)
        graph = self.bid_graph(ctx) if kind == "bid" else self.conv_graph(ctx)
        out = []
        async for s in graph.aget_state_history({"configurable": {"thread_id": thread_id}}):
            out.append({"checkpoint_id": s.config["configurable"]["checkpoint_id"], "next": list(s.next),
                        "step": s.metadata.get("step"), "status": s.values.get("status")})
        return out

    async def replay(self, thread_id: str, checkpoint_id: str, kind: str = "bid") -> AsyncIterator[dict]:
        """Re-run a job from any node: resume from a historical checkpoint (forks the thread)."""
        ctx = self.ctx_for(f"{thread_id}:replay:{uuid.uuid4().hex[:6]}")
        graph = self.bid_graph(ctx) if kind == "bid" else self.conv_graph(ctx)
        config = {"configurable": {"thread_id": thread_id, "checkpoint_id": checkpoint_id}}
        async for ev in self._drive(graph, ctx, None, config):
            yield ev
