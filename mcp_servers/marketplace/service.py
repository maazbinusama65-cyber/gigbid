"""Marketplace service: the guard pipeline every tool call goes through.

    user/trace resolution -> rate limit -> (idempotency replay) -> adapter call -> audit log

Kept independent of FastMCP so it is unit-testable and reusable by other front ends.
"""
from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from ..common.audit import AuditLog
from ..common.config import load_yaml_config, marketplace_mode
from ..common.idempotency import IdempotencyConflict, IdempotencyStore, fingerprint
from ..common.ratelimit import RateLimited, TokenBucketLimiter
from .adapters.base import AdapterError, MarketplaceAdapter

_USER_RE = re.compile(r"^[A-Za-z0-9_.@\-]{1,64}$")
DEFAULT_STATE_DIR = Path("data/processed/marketplace_mcp")
# Our own ceiling is deliberately well below GigSim's GIGSIM_RATE_LIMIT_RPM default (60).
DEFAULT_RPM = 20


@dataclass
class MarketplaceConfig:
    mode: str = "gigsim"  # gigsim | upwork_live
    default_user: str = field(default_factory=lambda: os.getenv("MARKETPLACE_DEFAULT_USER", "default"))
    rate_limit_rpm: float = DEFAULT_RPM
    rate_burst: int | None = None
    state_dir: str | Path = field(
        default_factory=lambda: os.getenv("MARKETPLACE_STATE_DIR", str(DEFAULT_STATE_DIR)))
    audit_path: str | Path | None = None
    idempotency_path: str | Path | None = None
    adapter: MarketplaceAdapter | None = None  # injected in tests
    clock: Callable[[], float] = time.monotonic

    @classmethod
    def from_yaml(cls, path: str | Path | None = None, **overrides: Any) -> MarketplaceConfig:
        y = load_yaml_config(path)
        m = y.get("marketplace", {})
        base = {"mode": marketplace_mode(y), "rate_limit_rpm": m.get("max_requests_per_minute", DEFAULT_RPM)}
        return cls(**{**base, **overrides})

    def resolved_audit_path(self) -> Path:
        return Path(self.audit_path or Path(self.state_dir) / "audit.jsonl")

    def resolved_idem_path(self) -> Path | str:
        return self.idempotency_path or Path(self.state_dir) / "idempotency.sqlite"


def build_adapter(cfg: MarketplaceConfig) -> MarketplaceAdapter:
    if cfg.adapter is not None:
        return cfg.adapter
    if cfg.mode == "gigsim":
        from .adapters.gigsim import GigSimAdapter

        return GigSimAdapter()
    if cfg.mode == "upwork_live":
        from .adapters.upwork_live import UpworkLiveAdapter

        return UpworkLiveAdapter()
    raise ValueError(f"unknown marketplace.mode {cfg.mode!r} (expected gigsim | upwork_live)")


Summarize = Callable[[dict[str, Any]], str]


class MarketplaceService:
    def __init__(self, cfg: MarketplaceConfig | None = None) -> None:
        self.cfg = cfg or MarketplaceConfig.from_yaml()
        self.adapter = build_adapter(self.cfg)
        self.limiter = TokenBucketLimiter(self.cfg.rate_limit_rpm, self.cfg.rate_burst, self.cfg.clock)
        self.audit = AuditLog(self.cfg.resolved_audit_path())
        self.idem = IdempotencyStore(self.cfg.resolved_idem_path())
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}

    # ------------------------------------------------------------------ guard pipeline
    async def execute(
        self,
        *,
        user: str,
        trace_id: str | None,
        tool: str,
        audit_args: dict[str, Any],
        run: Callable[[str], Awaitable[dict[str, Any]]],
        summarize: Summarize,
        write_key: str | None = None,
        fp_args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run ``run(user)`` under the guards. ``write_key`` turns on durable idempotency."""
        extra = {"idempotency_key": write_key} if write_key else None
        try:
            if not _USER_RE.match(user):
                raise ToolError("unauthorized: invalid user id")
            self.limiter.acquire(user)
            if write_key is None:
                result = await run(user)
            else:
                result = await self._idempotent(user, tool, write_key, fp_args or {}, run)
        except RateLimited as exc:
            self._log(user, tool, audit_args, str(exc), trace_id, False, extra)
            raise ToolError(str(exc)) from exc
        except IdempotencyConflict as exc:
            self._log(user, tool, audit_args, str(exc), trace_id, False, extra)
            raise ToolError(str(exc)) from exc
        except AdapterError as exc:
            msg = str(exc) + (f" (retry after {exc.retry_after:.1f}s)" if exc.retry_after else "")
            self._log(user, tool, audit_args, msg, trace_id, False, extra)
            raise ToolError(msg) from exc
        except ToolError as exc:
            self._log(user, tool, audit_args, str(exc), trace_id, False, extra)
            raise
        self._log(user, tool, audit_args, summarize(result), trace_id, True, extra)
        return result

    async def _idempotent(self, user, tool, key, fp_args, run):
        fp = fingerprint(fp_args)
        lock = self._locks.setdefault((user, tool, key), asyncio.Lock())
        async with lock:  # concurrent duplicates wait, then replay
            stored = self.idem.get(user, tool, key, fp)
            if stored is not None:
                return {**stored, "idempotent_replay": True}
            result = await run(user)
            self.idem.put(user, tool, key, fp, result)
            return result

    def _log(self, user, tool, args, result, trace_id, ok, extra):
        self.audit.record(user=user, tool=tool, arguments=args, result_summary=result,
                          trace_id=trace_id, ok=ok, extra=extra)

    # ------------------------------------------------------------------ composed operations
    async def preview_submit(self, user: str, proposal_id: str) -> dict[str, Any]:
        prop = await self.adapter.get_proposal(user, proposal_id)
        cost = prop.get("connects_cost")
        if cost is None and prop.get("job_id"):
            cost = (await self.adapter.get_job(user, prop["job_id"])).get("connects_cost")
        if cost is None:
            cost = (await self.adapter.get_policy(user)).get("connects_per_proposal", 0)
        bal = (await self.adapter.get_connects(user)).get("balance")
        if bal is not None and bal < int(cost):
            raise ToolError(f"insufficient_connects: need {cost}, balance {bal}")
        return {"proposal_id": proposal_id, "status": "preview", "connects_cost": int(cost),
                "balance_after": None if bal is None else bal - int(cost), "payload": prop,
                "dry_run": True}

    def check_owner(self, user: str, proposal_id: str) -> None:
        owner = self.idem.owner("proposal", proposal_id)
        if owner is not None and owner != user:
            raise ToolError("forbidden: proposal belongs to another user")

    async def aclose(self) -> None:
        await self.adapter.aclose()
        self.idem.close()


# ---------------------------------------------------------------------- result normalisers
def normalize_proposal(raw: dict[str, Any], *, dry_run: bool, submit: bool = False) -> dict[str, Any]:
    status = raw.get("status") or ("preview" if dry_run else ("submitted" if submit else "draft"))
    if status not in ("preview", "draft", "submitted"):
        status = "preview" if dry_run else "draft"
    cost = raw.get("connects_cost", raw.get("connects_spent", 0)) or 0
    return {
        "proposal_id": None if dry_run else raw.get("proposal_id"),
        "status": status,
        "connects_cost": int(cost),
        "balance_after": raw.get("balance_after", raw.get("balance")),
        "connects_spent": int(cost) if status == "submitted" else None,
        "balance": raw.get("balance_after", raw.get("balance")),
        "payload": raw.get("payload") or {"proposal_id": raw.get("proposal_id")},
        "dry_run": dry_run,
        "idempotent_replay": False,
        "requires_user_confirmation": bool(raw.get("requires_user_confirmation", False)),
        "note": raw.get("note"),
    }


def normalize_message(raw: dict[str, Any], *, thread_id: str, body: str, dry_run: bool) -> dict[str, Any]:
    status = raw.get("status") if raw.get("status") in ("preview", "draft", "sent") else None
    return {
        "message_id": None if dry_run else (raw.get("message_id") or raw.get("id")),
        "thread_id": thread_id,
        "status": status or ("preview" if dry_run else "sent"),
        "payload": raw.get("payload") or {"thread_id": thread_id, "body": body},
        "dry_run": dry_run,
        "idempotent_replay": False,
        "requires_user_confirmation": bool(raw.get("requires_user_confirmation", False)),
        "note": raw.get("note"),
    }


def normalize_market_stats(raw: dict[str, Any], category: str | None) -> dict[str, Any]:
    inner = raw.get(category) if category and isinstance(raw.get(category), dict) else None
    out = {**raw, **inner} if inner else dict(raw)
    out.setdefault("category", category)
    return out
