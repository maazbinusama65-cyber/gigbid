"""Live adapter: maps the OFFICIAL Upwork MCP server (https://mcp.upwork.com/mcp) onto the same
adapter contract GigSim implements, so the agent graph cannot tell which marketplace is live.

Safety rules enforced here (assignment A4):
  * writes only ever create DRAFTS: there is deliberately no code path that calls a "submit" or
    "send" tool on Upwork; ``submit_proposal`` / ``send_message`` return status "draft" with
    ``requires_user_confirmation`` and the user confirms on Upwork itself;
  * reads are cached (``read_cache_ttl``) so repeated calls never hit the platform in a
    scraping-like pattern; the polling schedule lives in the worker (config
    marketplace.live_poll_interval_minutes);
  * no browser automation, no cookies, no scraping: the only transport is MCP over Streamable HTTP
    with the user's OAuth bearer token (see upwork_oauth.py).

HONESTY NOTE: the real server's tool names/shapes were not verifiable from this repo (no
credentials, no public tool list). ``DEFAULT_TOOL_MAP`` holds PLACEHOLDER names; run
``python -m mcp_servers.marketplace.adapters.upwork_live --list-tools <user>`` after connecting an
account and override the map via env UPWORK_TOOL_MAP (JSON). Everything here is unit-tested against
a fake MCP session only.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from .base import AdapterError
from .upwork_oauth import (  # noqa: F401  (re-exported OAuth helper surface)
    AuthFlow,
    EncryptedTokenStore,
    OAuthConfig,
    OAuthError,
    TokenSet,
    build_authorization_url,
    discover_endpoints,
    exchange_code,
    generate_pkce,
    refresh_tokens,
)

UPWORK_MCP_URL = "https://mcp.upwork.com/mcp"

# adapter operation -> Upwork MCP tool name. PLACEHOLDERS, see module docstring.
# create_proposal_draft / create_message_draft are the ONLY write tools that can ever be called.
DEFAULT_TOOL_MAP: dict[str, str | None] = {
    "search_jobs": "search_jobs",
    "get_job": "get_job",
    "get_client": "get_client",
    "get_connects": "get_connects_balance",
    "list_messages": "list_messages",
    "list_threads": "list_threads",
    "list_events": None,                 # unsupported unless the server offers an activity feed
    "get_market_stats": None,            # no price statistics on the platform side
    "create_proposal_draft": "create_proposal_draft",
    "create_message_draft": "create_message_draft",
}
WRITE_OPERATIONS = {"create_proposal_draft", "create_message_draft"}
CONFIRM_NOTE = "Saved as a draft. Open Upwork to review and confirm; GigBid never submits on Upwork."

SessionFactory = Callable[[str, str], AbstractAsyncContextManager[Any]]


def tool_map_from_env() -> dict[str, str | None]:
    merged = dict(DEFAULT_TOOL_MAP)
    raw = os.getenv("UPWORK_TOOL_MAP")
    if raw:
        merged.update(json.loads(raw))
    return merged


def parse_tool_result(result: Any) -> Any:
    """CallToolResult -> python object (structuredContent first, then JSON text)."""
    if getattr(result, "isError", False):
        text = " ".join(getattr(c, "text", "") for c in getattr(result, "content", []))[:300]
        raise AdapterError("upstream_rejected", f"Upwork tool error: {text}")
    sc = getattr(result, "structuredContent", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    for c in getattr(result, "content", []):
        text = getattr(c, "text", None)
        if text:
            try:
                return json.loads(text)
            except ValueError:
                return {"text": text}
    return {}


def _first(d: dict, *keys: str, default: Any = None) -> Any:
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


def normalize_job(raw: dict[str, Any]) -> dict[str, Any]:
    b = raw.get("budget")
    if not isinstance(b, dict):
        amount = _first(raw, "amount", "budget_amount", "fixed_price")
        b = {"type": "fixed", "min": amount, "max": amount, "currency": "USD"} if amount else None
    return {
        "job_id": str(_first(raw, "job_id", "id", "ciphertext", default="")),
        "client_id": _first(raw, "client_id", "buyer_id"),
        "title": _first(raw, "title", default=""),
        "description": _first(raw, "description", default=""),
        "category": _first(raw, "category"),
        "required_skills": list(_first(raw, "required_skills", "skills", default=[])),
        "budget": b,
        "duration_days": _first(raw, "duration_days"),
        "screening_questions": list(_first(raw, "screening_questions", "questions", default=[])),
        "posted_at": _first(raw, "posted_at", "created_at"),
        "connects_cost": _first(raw, "connects_cost", "connects_required"),
    }


class UpworkLiveAdapter:
    name = "upwork_live"

    def __init__(
        self,
        *,
        token_store: EncryptedTokenStore | None = None,
        oauth: OAuthConfig | None = None,
        session_factory: SessionFactory | None = None,
        tool_map: dict[str, str | None] | None = None,
        url: str = UPWORK_MCP_URL,
        read_cache_ttl: float = 300.0,
        connects_per_proposal: int = 8,
        rate_limit_rpm: int = 20,
        clock: Callable[[], float] = time.monotonic,
        http: Any = None,
    ) -> None:
        self.url = url
        self.tool_map = {**DEFAULT_TOOL_MAP, **(tool_map or {})} if tool_map is not None else tool_map_from_env()
        self._store = token_store
        self._oauth = oauth
        self._http = http
        self._session_factory = session_factory or self._default_session
        self.read_cache_ttl, self._clock = read_cache_ttl, clock
        self.connects_per_proposal, self.rate_limit_rpm = connects_per_proposal, rate_limit_rpm
        self._cache: dict[tuple, tuple[float, Any]] = {}

    # ------------------------------------------------------------------ auth + transport
    @property
    def store(self) -> EncryptedTokenStore:
        if self._store is None:
            self._store = EncryptedTokenStore(
                os.getenv("UPWORK_TOKEN_STORE", "data/processed/upwork_tokens.enc.json"))
        return self._store

    async def _access_token(self, user: str) -> str:
        try:
            tokens = self.store.get(user)
            if tokens is None:
                raise AdapterError("unauthorized", "Upwork account not connected for this user")
            if tokens.is_expired():
                if self._oauth is None:
                    raise AdapterError("unauthorized", "Upwork token expired and OAuth is not configured")
                tokens = await refresh_tokens(self._oauth.token_endpoint, client_id=self._oauth.client_id,
                                              tokens=tokens, client_secret=self._oauth.client_secret,
                                              http=self._http)
                self.store.put(user, tokens)
            return tokens.access_token
        except OAuthError as exc:
            raise AdapterError("unauthorized", str(exc)) from exc

    @asynccontextmanager
    async def _default_session(self, user: str, token: str):
        from langchain_mcp_adapters.client import MultiServerMCPClient

        client = MultiServerMCPClient({"upwork": {
            "transport": "streamable_http", "url": self.url,
            "headers": {"Authorization": f"Bearer {token}"}}})
        async with client.session("upwork") as session:
            yield session

    async def _call_tool(self, user: str, op: str, args: dict[str, Any]) -> Any:
        tool = self.tool_map.get(op)
        if not tool:
            raise AdapterError("unsupported", f"'{op}' is not available on the live marketplace")
        token = await self._access_token(user)
        try:
            async with self._session_factory(user, token) as session:
                result = await session.call_tool(tool, {k: v for k, v in args.items() if v is not None})
        except AdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - network/protocol failure; never include token
            raise AdapterError("upstream_unavailable", f"Upwork MCP call failed: {type(exc).__name__}") from exc
        return parse_tool_result(result)

    async def _cached_read(self, user: str, op: str, args: dict[str, Any]) -> Any:
        key = (user, op, json.dumps(args, sort_keys=True, default=str))
        hit = self._cache.get(key)
        now = self._clock()
        if hit and now - hit[0] < self.read_cache_ttl:
            return hit[1]
        value = await self._call_tool(user, op, args)
        self._cache[key] = (now, value)
        return value

    async def list_tools(self, user: str) -> list[str]:
        """Discover the server's real tool names (use this to fix ``tool_map``)."""
        token = await self._access_token(user)
        async with self._session_factory(user, token) as session:
            return [t.name for t in (await session.list_tools()).tools]

    async def aclose(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------ reads
    async def search_jobs(self, user, *, q=None, category=None, skills=None, since=None, limit=20,
                          cursor=None):
        raw = await self._cached_read(user, "search_jobs", {
            "query": q, "category": category, "skills": skills, "limit": limit, "cursor": cursor})
        jobs = raw if isinstance(raw, list) else raw.get("jobs", [])
        return {"jobs": [normalize_job(j) for j in jobs],
                "next_cursor": None if isinstance(raw, list) else raw.get("next_cursor")}

    async def get_job(self, user, job_id):
        return normalize_job(await self._cached_read(user, "get_job", {"job_id": job_id}))

    async def get_client(self, user, client_id):
        raw = await self._cached_read(user, "get_client", {"client_id": client_id})
        return {**raw, "client_id": str(_first(raw, "client_id", "id", default=client_id)),
                "history": list(raw.get("history", []))}

    async def get_connects(self, user):
        raw = await self._cached_read(user, "get_connects", {})
        return {"balance": int(_first(raw, "balance", "connects", default=0)),
                "weekly_allowance": raw.get("weekly_allowance"),
                "spent_this_week": raw.get("spent_this_week")}

    async def get_market_stats(self, user, category=None, skills=None):
        raise AdapterError("unsupported", "market price statistics are not available on the live "
                                           "marketplace; price from the local history stats instead")

    async def get_policy(self, user):
        return {"version": "upwork-live-static", "connects_per_proposal": self.connects_per_proposal,
                "rate_limit_rpm": self.rate_limit_rpm, "rules": [],
                "note": "Upwork exposes no machine-readable policy; GigBid's local policy pack applies."}

    async def list_messages(self, user, thread_id=None):
        if thread_id:
            raw = await self._cached_read(user, "list_messages", {"thread_id": thread_id})
            return {"thread_id": thread_id, "messages": raw if isinstance(raw, list) else raw.get("messages", [])}
        raw = await self._cached_read(user, "list_threads", {})
        return {"threads": raw if isinstance(raw, list) else raw.get("threads", [])}

    async def list_events(self, user, since=None):
        raw = await self._cached_read(user, "list_events", {"since": since})
        return raw if isinstance(raw, list) else raw.get("events", [])

    async def get_proposal(self, user, proposal_id):
        raise AdapterError("unsupported", "proposal lookup is not available on the live marketplace")

    # ------------------------------------------------------------------ writes: DRAFTS ONLY
    async def create_proposal(self, user, payload, idempotency_key, dry_run):
        job = await self.get_job(user, payload["job_id"])
        cost = job.get("connects_cost") or self.connects_per_proposal
        bal = (await self.get_connects(user))["balance"]
        if dry_run:
            return {"proposal_id": None, "status": "preview", "connects_cost": cost,
                    "balance_after": bal - cost, "payload": payload}
        raw = await self._call_tool(user, "create_proposal_draft", {**payload, "client_reference": idempotency_key})
        pid = str(_first(raw, "proposal_id", "id", "draft_id", default=""))
        return {"proposal_id": pid or None, "status": "draft", "connects_cost": cost,
                "balance_after": bal, "payload": payload, "requires_user_confirmation": True,
                "note": CONFIRM_NOTE}

    async def submit_proposal(self, user, proposal_id, idempotency_key):
        # NEVER calls Upwork: the user confirms the draft on the platform.
        return {"proposal_id": proposal_id, "status": "draft", "connects_cost": 0,
                "payload": {"proposal_id": proposal_id}, "requires_user_confirmation": True,
                "note": CONFIRM_NOTE}

    async def send_message(self, user, thread_id, body, idempotency_key):
        raw = await self._call_tool(user, "create_message_draft", {
            "thread_id": thread_id, "body": body, "client_reference": idempotency_key})
        return {"message_id": _first(raw, "message_id", "id", "draft_id"), "status": "draft",
                "payload": {"thread_id": thread_id, "body": body}, "requires_user_confirmation": True,
                "note": CONFIRM_NOTE}


def _cli(argv: list[str] | None = None) -> None:  # pragma: no cover - needs live credentials
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(prog="upwork_live")
    ap.add_argument("--list-tools", metavar="USER", required=True)
    args = ap.parse_args(argv)
    print("\n".join(asyncio.run(UpworkLiveAdapter().list_tools(args.list_tools))))


if __name__ == "__main__":  # pragma: no cover
    _cli()
