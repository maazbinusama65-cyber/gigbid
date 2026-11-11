"""Shared node plumbing: runtime context, instrumentation (trace, retries, timeouts, budgets)."""
from __future__ import annotations

import asyncio
import functools
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from langgraph.errors import GraphBubbleUp

from agent.config_loader import Config
from agent.llm import LLM, UsageTracker, reset_tracker, set_tracker
from agent.memory.store import LongTermMemory
from agent.policy import Policy
from agent.trace import TraceRecorder

log = logging.getLogger("gigbid.nodes")

HALT = {"skipped", "rejected", "blocked", "needs_attention", "dead_letter", "submitted", "flagged"}


class ToolUnavailable(RuntimeError):  # mirrors agent.tools.ToolUnavailable if that is importable
    pass


try:  # prefer the gateway's own exception types so `except` clauses match
    from agent.tools import ToolUnavailable as ToolUnavailable  # type: ignore  # noqa: F811
except Exception:  # pragma: no cover - gateway not yet importable
    pass


@dataclass
class Ctx:
    """Everything a node may touch. Nodes never import tool servers or the marketplace directly."""

    cfg: Config
    llm: LLM
    tools: Any                      # agent.tools.ToolGateway-compatible: await call(agent, tool, args)
    memory: LongTermMemory
    policy: Policy
    recorder: TraceRecorder | None = None
    tracker: UsageTracker = field(default_factory=UsageTracker)
    user_llm_nodes: set[str] | None = None

    def use_llm(self, node: str) -> bool:
        nodes = self.user_llm_nodes if self.user_llm_nodes is not None else set(self.cfg.get("llm_nodes", []))
        return self.llm.available and node in nodes

    async def call(self, agent: str, tool: str, args: dict | None = None) -> Any:
        """One MCP tool call, traced. Raises ToolUnavailable in degraded mode."""
        t0 = time.monotonic()
        args = args or {}
        try:
            res = await self.tools.call(agent, tool, args)
            self._trace("tool", agent, tool=tool, args=args, ok=True, latency_s=round(time.monotonic() - t0, 3),
                        result=_digest(res))
            return res
        except Exception as e:
            self._trace("tool", agent, tool=tool, args=args, ok=False, error=str(e)[:200],
                        latency_s=round(time.monotonic() - t0, 3))
            raise

    def _trace(self, type_: str, node: str | None, **data: Any) -> None:
        if self.recorder:
            self.recorder.event(type_, node, **data)


def _digest(res: Any, limit: int = 600) -> Any:
    s = str(res)
    return s if len(s) <= limit else s[:limit] + f"...[{len(s)} chars]"


def instrument(name: str, ctx: Ctx, fn):
    """Wrap a node: trace events, step/token budgets, per-node timeout + bounded retry, dead-letter."""
    retries = int(ctx.cfg.get_path("nodes.retries", 1))
    timeout = float(ctx.cfg.get_path("nodes.timeout_seconds", 90))
    max_steps = int(ctx.cfg["budgets"]["max_graph_steps"])
    max_tokens = int(ctx.cfg["budgets"]["max_tokens_per_job"])

    @functools.wraps(fn)
    async def wrapper(state: dict) -> dict:
        if int(state.get("steps", 0)) >= max_steps:
            ctx._trace("budget", name, kind="steps")
            return {"status": "needs_attention", "status_reason": f"step budget {max_steps} exceeded"}
        if ctx.tracker.total_tokens > max_tokens:
            ctx._trace("budget", name, kind="tokens", used=ctx.tracker.total_tokens)
            return {"status": "needs_attention", "status_reason": f"token budget {max_tokens} exceeded"}
        ctx._trace("node_start", name)
        t0 = time.monotonic()
        tok = set_tracker(ctx.tracker)
        last: Exception | None = None
        try:
            for attempt in range(retries + 1):
                try:
                    out = await asyncio.wait_for(fn(state, ctx), timeout)
                    out = dict(out or {})
                    out["steps"] = 1
                    ctx._trace("node_end", name, latency_s=round(time.monotonic() - t0, 3),
                               tokens=ctx.tracker.total_tokens, cost_usd=round(ctx.tracker.total_cost, 6),
                               keys=sorted(out.keys()), status=out.get("status"))
                    return out
                except GraphBubbleUp:  # interrupt() / control flow must reach the runtime untouched
                    raise
                except ToolUnavailable as e:
                    ctx._trace("degraded", name, error=str(e)[:200])
                    return {"status": "needs_attention", "status_reason": f"marketplace_unavailable: {e}",
                            "errors": [f"{name}: tool unavailable"], "steps": 1}
                except Exception as e:  # noqa: BLE001 - per-node retry boundary
                    last = e
                    ctx._trace("node_error", name, attempt=attempt, error=str(e)[:300])
                    await asyncio.sleep(0.2 * (attempt + 1))
            return {"status": "dead_letter", "status_reason": f"{name} failed: {str(last)[:200]}",
                    "errors": [f"{name}: {str(last)[:200]}"], "steps": 1}
        finally:
            reset_tracker(tok)

    return wrapper


def route_unless_halted(next_node: str):
    from langgraph.graph import END

    def _r(state: dict) -> str:
        return END if state.get("status") in HALT else next_node

    return _r


_WORD = re.compile(r"[A-Za-z0-9+#.\-]+")


def words(text: str) -> list[str]:
    return _WORD.findall(text or "")


def first_sentences(text: str, n: int = 2, limit: int = 260) -> str:
    text = re.sub(r"^#+\s.*$", "", text or "", flags=re.M)          # drop markdown headings
    text = re.sub(r"[`*_>\[\]]+", "", text)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 25]
    out = " ".join(sents[:n])
    return out[:limit].rstrip()
