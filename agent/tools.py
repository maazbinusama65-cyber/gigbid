"""ToolGateway: the one place agents call MCP tools through (A6).

    await gateway.call("pricing", "get_market_stats", {"category": "ml"}) -> dict

* allowlist per agent, by tool name (``ToolNotAllowed``)
* timeout per attempt, bounded retries with exponential backoff
* degraded mode: after retries are exhausted the server is marked degraded, calls fail fast with
  ``ToolUnavailable`` (writes with an idempotency key are QUEUED and replayed by ``recover()``),
  and ``status()`` gives the UI a message to show
* execution trace: every call appends a masked record to ``gateway.trace``
* transports: ``memory`` (in-process FastMCP through ``mcp.shared.memory``: tests/evals, same
  schemas) or ``http`` (``MultiServerMCPClient`` over Streamable HTTP), from ``tool_servers.transport``
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from agent.guardrails import mask_obj
from agent.mcp_client import (
    APPROVAL_REQUIRED_TOOLS,
    WRITE_TOOLS,
    allowed_tools,
    build_connections,
    server_for,
)

log = logging.getLogger("gigbid.tools")

# tool-level error codes (the MCP servers prefix errors with "<code>: ") that are worth retrying
RETRY_CODES = {"rate_limited", "upstream_rate_limited"}
DEGRADE_CODES = {"upstream_unavailable"}
KNOWN_CODES = RETRY_CODES | DEGRADE_CODES | {
    "not_found", "forbidden", "unauthorized", "unsupported", "upstream_rejected", "idempotency_conflict",
    "insufficient_connects", "invalid_slot", "slot_unavailable",
}
MAX_TRACE = 5000
MAX_BACKOFF = 5.0


# --------------------------------------------------------------------------- errors
class ToolError(Exception):
    """Base class for gateway errors."""


class ToolNotAllowed(ToolError, PermissionError):
    """The agent's allowlist does not include this tool (or the tool does not exist)."""


class ApprovalRequired(ToolNotAllowed):
    """strict approval mode: a real write was attempted without approved=True."""


class ToolUnavailable(ToolError, RuntimeError):
    """The tool server (or the marketplace behind it) is down. ``queued`` is True when the write
    was stored and will be replayed by ``ToolGateway.recover()``."""

    def __init__(self, message: str, *, server: str = "", queued: bool = False) -> None:
        super().__init__(message)
        self.server, self.queued = server, queued


class ToolCallFailed(ToolError):
    """The server answered with a tool error (validation, not_found, forbidden, rate limit...)."""

    def __init__(self, tool: str, code: str, message: str) -> None:
        super().__init__(f"{tool}: {code}: {message}")
        self.tool, self.code, self.message = tool, code, message


# --------------------------------------------------------------------------- state
@dataclass
class ServerHealth:
    state: str = "unknown"          # unknown | up | degraded
    consecutive_failures: int = 0
    last_error: str | None = None
    since: float | None = None
    last_ok: float | None = None
    open_until: float = 0.0         # fail fast until this time (circuit breaker)


@dataclass
class QueuedCall:
    agent: str
    tool: str
    args: dict[str, Any]
    trace_id: str | None
    approved: bool
    server: str
    queued_at: float = field(default_factory=time.time)


@dataclass
class _Shared:
    """Connections, health, queue and trace shared by a gateway and all its ``for_run`` views."""

    transport: str
    timeout: float
    retries: int
    backoff: float
    cooldown: float
    memory_servers: dict[str, Any]
    connections: dict[str, dict[str, Any]]
    clock: Callable[[], float]
    sleep: Callable[[float], Awaitable[None]]
    health: dict[str, ServerHealth] = field(default_factory=dict)
    queue: list[QueuedCall] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    client: Any = None


def _describe(exc: BaseException) -> str:
    """Short, secret-free description of a (possibly grouped) transport failure."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {str(exc)[:120]}" if str(exc) else type(exc).__name__


def _parse_tool_error(tool: str, text: str) -> tuple[str, str, float | None]:
    body = re.sub(r"^Error executing tool \S+:\s*", "", text.strip())
    m = re.match(r"([a-z_]+):\s*(.*)", body, re.S)
    code, msg = (m.group(1), m.group(2)) if m and m.group(1) in KNOWN_CODES else (None, body)
    if code is None:
        code = "invalid_arguments" if "validation error" in body else "tool_error"
    ra = re.search(r"retry after ([\d.]+)s", body)
    return code, msg[:300], float(ra.group(1)) if ra else None


def _result_to_dict(res: Any) -> dict[str, Any]:
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        return sc
    for c in getattr(res, "content", None) or []:
        text = getattr(c, "text", None)
        if text:
            try:
                val = json.loads(text)
            except ValueError:
                return {"text": text}
            return val if isinstance(val, dict) else {"result": val}
    return {}


def _digest(res: dict[str, Any], limit: int = 300) -> str:
    s = json.dumps(mask_obj(res), default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + f"...[{len(s)} chars]"


def _trim(obj: Any, limit: int = 200) -> Any:
    if isinstance(obj, str):
        return obj if len(obj) <= limit else obj[:limit] + f"...[+{len(obj) - limit}]"
    if isinstance(obj, dict):
        return {k: _trim(v, limit) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_trim(v, limit) for v in obj[:20]]
    return obj


# --------------------------------------------------------------------------- gateway
class ToolGateway:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        user_id: str = "default",
        transport: str | None = None,
        servers: Mapping[str, Any] | None = None,
        approval_mode: str = "trust_graph",
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        trace_id: str | None = None,
        _shared: _Shared | None = None,
    ) -> None:
        self.user_id = user_id
        self.approval_mode = approval_mode  # trust_graph | strict
        self._trace_id = trace_id
        if _shared is not None:
            self._shared = _shared
            return
        ts = dict((config or {}).get("tool_servers", {}) or {})
        mode = transport or os.getenv("TOOL_TRANSPORT") or ts.get("transport", "memory")
        if mode not in ("memory", "http"):
            raise ValueError(f"tool_servers.transport must be 'memory' or 'http', got {mode!r}")
        self._shared = _Shared(
            transport=mode,
            timeout=float(ts.get("timeout_seconds", 20)),
            retries=int(ts.get("retries", 3)),
            backoff=float(ts.get("backoff_seconds", 0.5)),
            cooldown=float(ts.get("cooldown_seconds", 10)),
            memory_servers=servers if isinstance(servers, dict) else dict(servers or {}),  # live dict: tests can kill/revive
            connections=build_connections(config, user_id) if mode == "http" else {},
            clock=clock,
            sleep=sleep or asyncio.sleep,
        )
        self._shared.health = {}
        self._default_servers_loaded = servers is not None

    # ------------------------------------------------------------------ views
    def for_run(self, trace_id: str, user_id: str | None = None) -> ToolGateway:
        """Lightweight view sharing connections, health, queue and trace; records carry ``trace_id``."""
        return ToolGateway(user_id=user_id or self.user_id, approval_mode=self.approval_mode,
                           trace_id=trace_id, _shared=self._shared)

    @property
    def trace(self) -> list[dict[str, Any]]:
        """Records (agent, tool, args masked, result_digest, latency_s, ok, trace_id, ...).
        On a ``for_run`` view only that run's records."""
        recs = self._shared.trace
        return [r for r in recs if r["trace_id"] == self._trace_id] if self._trace_id else list(recs)

    def trace_for(self, trace_id: str) -> list[dict[str, Any]]:
        return [r for r in self._shared.trace if r["trace_id"] == trace_id]

    # ------------------------------------------------------------------ public API
    async def call(self, agent: str, tool: str, args: Mapping[str, Any] | None = None,
                   trace_id: str | None = None, *, approved: bool = False) -> dict[str, Any]:
        args = dict(args or {})
        tid = trace_id or self._trace_id
        t0 = time.monotonic()
        meta = {"agent": agent, "tool": tool, "args": _trim(mask_obj(args)), "trace_id": tid}
        server = None
        try:
            server = self._authorize(agent, tool, args, approved)
            result, attempts = await self._invoke(server, tool, args, tid)
        except ToolUnavailable as exc:
            exc.server = exc.server or server or ""
            if server and self._queueable(tool, args):
                self._enqueue(QueuedCall(agent, tool, args, tid, approved, server))
                exc.queued = True
            self._record(meta, server, t0, ok=False, error=f"unavailable: {exc}", queued=exc.queued)
            raise
        except ToolError as exc:
            self._record(meta, server, t0, ok=False, error=f"{type(exc).__name__}: {exc}")
            raise
        self._record(meta, server, t0, ok=True, digest=_digest(result), attempts=attempts)
        return result

    def allowed(self, agent: str) -> dict[str, list[str]]:
        return {s: sorted(t) for s, t in allowed_tools(agent).items()}

    def status(self) -> dict[str, Any]:
        """UI-facing health. ``message`` is ready to show when something is degraded."""
        sh, now = self._shared, self._shared.clock()
        servers: dict[str, Any] = {}
        for name, h in sh.health.items():
            servers[name] = {
                "state": h.state, "consecutive_failures": h.consecutive_failures,
                "last_error": h.last_error, "retry_in_s": max(0.0, round(h.open_until - now, 1)),
                "queued_writes": sum(1 for q in sh.queue if q.server == name),
            }
        degraded = sorted(n for n, s in servers.items() if s["state"] == "degraded")
        msg = None
        if degraded:
            queued = sum(servers[n]["queued_writes"] for n in degraded)
            msg = (f"{', '.join(degraded)} tools are unavailable; read-only work is paused"
                   + (f" and {queued} action(s) are queued and will be sent automatically on recovery"
                      if queued else "") + ". Retrying shortly.")
        return {"ok": not degraded, "transport": sh.transport, "degraded": degraded,
                "servers": servers, "queued": len(sh.queue), "message": msg}

    async def probe(self, server: str) -> bool:
        """Liveness check (list_tools). Updates health; True when the server answers."""
        sh = self._shared
        try:
            await asyncio.wait_for(self._list(server), sh.timeout)
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(server, _describe(exc))
            return False
        self._mark_up(server)
        return True

    async def recover(self) -> dict[str, Any]:
        """Probe degraded servers; for those that are back, replay queued writes in order."""
        sh = self._shared
        recovered, replayed, failed = [], [], []
        for name in [n for n, h in sh.health.items() if h.state == "degraded"]:
            if await self.probe(name):
                recovered.append(name)
        pending, sh.queue = sh.queue, []
        for i, q in enumerate(pending):
            if sh.health[q.server].state == "degraded":
                sh.queue.extend(pending[i:])   # still down: keep the rest, in order
                break
            try:
                res = await self.call(q.agent, q.tool, q.args, q.trace_id, approved=q.approved)
                replayed.append({"tool": q.tool, "result": res})
            except ToolUnavailable:
                sh.queue = [x for x in sh.queue if x is not q]
                sh.queue.extend(pending[i:])
                break
            except ToolError as exc:
                failed.append({"tool": q.tool, "error": str(exc)})
        return {"recovered": recovered, "replayed": replayed, "failed": failed, "still_queued": len(sh.queue)}

    async def aclose(self) -> None:
        self._shared.client = None

    # ------------------------------------------------------------------ internals
    def _authorize(self, agent: str, tool: str, args: dict[str, Any], approved: bool) -> str:
        server = server_for(agent, tool)
        if server is None:
            raise ToolNotAllowed(f"agent {agent!r} may not call tool {tool!r}")
        if (self.approval_mode == "strict" and tool in APPROVAL_REQUIRED_TOOLS
                and not args.get("dry_run") and not approved):
            raise ApprovalRequired(f"{tool} needs explicit human approval (approved=True)")
        self._shared.health.setdefault(server, ServerHealth())
        return server

    @staticmethod
    def _queueable(tool: str, args: dict[str, Any]) -> bool:
        return tool in WRITE_TOOLS and not args.get("dry_run") and bool(args.get("idempotency_key"))

    def _enqueue(self, q: QueuedCall) -> None:
        key = (q.tool, q.args.get("idempotency_key"))
        if not any((x.tool, x.args.get("idempotency_key")) == key for x in self._shared.queue):
            self._shared.queue.append(q)

    def _record(self, meta: dict[str, Any], server: str | None, t0: float, *, ok: bool,
                digest: str | None = None, error: str | None = None, attempts: int | None = None,
                queued: bool = False) -> None:
        rec = {**meta, "server": server, "result_digest": digest, "latency_s": round(time.monotonic() - t0, 4),
               "ok": ok, "error": error, "attempts": attempts, "queued": queued, "ts": time.time()}
        tr = self._shared.trace
        tr.append(rec)
        if len(tr) > MAX_TRACE:
            del tr[: len(tr) - MAX_TRACE]

    def _mark_up(self, server: str) -> None:
        h = self._shared.health.setdefault(server, ServerHealth())
        h.state, h.consecutive_failures, h.last_error, h.open_until = "up", 0, None, 0.0
        h.last_ok, h.since = self._shared.clock(), None

    def _mark_degraded(self, server: str, error: str) -> None:
        sh = self._shared
        h = sh.health.setdefault(server, ServerHealth())
        if h.state != "degraded":
            h.since = sh.clock()
            log.warning("tool server %s degraded: %s", server, error)
        h.state, h.last_error = "degraded", error
        h.consecutive_failures += 1
        h.open_until = sh.clock() + sh.cooldown

    async def _invoke(self, server: str, tool: str, args: dict[str, Any], tid: str | None):
        sh = self._shared
        h = sh.health.setdefault(server, ServerHealth())
        if h.state == "degraded" and sh.clock() < h.open_until:   # circuit open: fail fast
            raise ToolUnavailable(f"{server} is degraded ({h.last_error})", server=server)
        meta = {"user_id": self.user_id, **({"trace_id": tid} if tid else {})}
        last_error, last_code, wait = "unknown", None, None
        for attempt in range(1, sh.retries + 2):
            wait = None
            try:
                res = await asyncio.wait_for(self._once(server, tool, args, meta), sh.timeout)
            except TimeoutError:
                last_error, last_code = f"timeout after {sh.timeout:g}s", "timeout"
            except Exception as exc:  # noqa: BLE001 - transport failure of any shape
                last_error, last_code = _describe(exc), "transport"
            else:
                if not getattr(res, "isError", False):
                    self._mark_up(server)
                    return _result_to_dict(res), attempt
                text = " ".join(getattr(c, "text", "") or "" for c in getattr(res, "content", []))
                code, msg, wait = _parse_tool_error(tool, text)
                if code not in RETRY_CODES | DEGRADE_CODES:
                    self._mark_up(server)           # server is fine; the call itself was rejected
                    raise ToolCallFailed(tool, code, msg)
                last_error, last_code = f"{code}: {msg}", code
            if attempt <= sh.retries:
                await sh.sleep(min(wait if wait is not None else sh.backoff * 2 ** (attempt - 1), MAX_BACKOFF))
        if last_code in RETRY_CODES:                # persistent rate limit is not an outage
            self._mark_up(server)
            raise ToolCallFailed(tool, last_code, last_error)
        self._mark_degraded(server, last_error)
        raise ToolUnavailable(f"{server} unavailable after {sh.retries + 1} attempt(s): {last_error}",
                              server=server)

    # -- transports --
    def _memory_server(self, server: str) -> Any:
        sh = self._shared
        if not sh.memory_servers and not getattr(self, "_default_servers_loaded", False):
            sh.memory_servers.update(default_memory_servers())
            self._default_servers_loaded = True
        target = sh.memory_servers.get(server)
        if target is None:
            raise ConnectionError(f"{server} server is not running")
        return target

    @asynccontextmanager
    async def _session(self, server: str):
        sh = self._shared
        if sh.transport == "memory":
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(
                self._memory_server(server), read_timeout_seconds=timedelta(seconds=sh.timeout)
            ) as session:
                yield session
        else:
            if sh.client is None:
                from langchain_mcp_adapters.client import MultiServerMCPClient

                sh.client = MultiServerMCPClient(sh.connections)
            async with sh.client.session(server) as session:
                yield session

    async def _once(self, server: str, tool: str, args: dict[str, Any], meta: dict[str, Any]):
        async with self._session(server) as session:
            return await session.call_tool(tool, args, meta=meta)

    async def _list(self, server: str):
        async with self._session(server) as session:
            return await session.list_tools()


def default_memory_servers() -> dict[str, Any]:
    """In-process servers built from agent/config.yaml (marketplace adapter per marketplace.mode)."""
    from mcp_servers.marketplace import build_server as marketplace
    from mcp_servers.portfolio import build_server as portfolio
    from mcp_servers.workspace import build_server as workspace

    return {"marketplace": marketplace(), "portfolio": portfolio(), "workspace": workspace()}
