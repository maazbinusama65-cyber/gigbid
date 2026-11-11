"""One marketplace port (R1).

``MarketplacePort`` is what the rest of GigBid is allowed to know. ``McpMarketplacePort`` implements
it over the Marketplace MCP server, through ``ToolGateway`` (allowlists, retries, degraded mode,
trace). Which marketplace answers (GigSim or live Upwork) is decided server-side by
``marketplace.mode``; the caller cannot tell.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from agent.tools import ToolGateway


@runtime_checkable
class MarketplacePort(Protocol):
    # ---- reads
    async def search_jobs(self, query: str = "", *, category: str | None = None,
                          skills: list[str] | None = None, limit: int = 20, since: str | None = None,
                          cursor: str | None = None) -> list[dict[str, Any]]: ...
    async def get_job(self, job_id: str) -> dict[str, Any]: ...
    async def get_client_history(self, client_id: str) -> dict[str, Any]: ...
    async def get_connects_balance(self) -> dict[str, Any]: ...
    async def get_market_stats(self, category: str | None = None,
                               skills: list[str] | None = None) -> dict[str, Any]: ...
    async def get_platform_policy(self) -> dict[str, Any]: ...
    async def list_messages(self, thread_id: str | None = None) -> dict[str, Any]: ...
    async def list_events(self, since: str | None = None) -> list[dict[str, Any]]: ...
    # ---- writes (idempotency key required; dry_run previews without side effects)
    async def create_proposal_draft(self, payload: dict[str, Any], idempotency_key: str,
                                    dry_run: bool = False) -> dict[str, Any]: ...
    async def submit_proposal(self, proposal_id: str, idempotency_key: str,
                              dry_run: bool = False) -> dict[str, Any]: ...
    async def send_message(self, thread_id: str, body: str, idempotency_key: str,
                           dry_run: bool = False) -> dict[str, Any]: ...


class McpMarketplacePort:
    """Port bound to one agent identity (its allowlist decides which methods work).

    ``McpMarketplacePort(gw, "pricing")`` can only read stats; ``.as_agent("submitter")`` returns
    a sibling with the executor's rights; ``.with_approval()`` marks real writes as human-approved
    (needed when the gateway runs in ``approval_mode="strict"``).
    """

    def __init__(self, gateway: ToolGateway, agent: str = "client_liaison", *,
                 approved: bool = False) -> None:
        self.gateway, self.agent, self.approved = gateway, agent, approved

    def as_agent(self, agent: str) -> McpMarketplacePort:
        return McpMarketplacePort(self.gateway, agent, approved=self.approved)

    def with_approval(self) -> McpMarketplacePort:
        return McpMarketplacePort(self.gateway, self.agent, approved=True)

    def _call(self, tool: str, args: dict[str, Any]):
        return self.gateway.call(self.agent, tool, {k: v for k, v in args.items() if v is not None},
                                 approved=self.approved)

    # ---- reads
    async def search_jobs(self, query: str = "", *, category: str | None = None,
                          skills: list[str] | None = None, limit: int = 20, since: str | None = None,
                          cursor: str | None = None) -> list[dict[str, Any]]:
        res = await self._call("search_jobs", {"query": query or None, "category": category, "skills": skills,
                                               "limit": limit, "since": since, "cursor": cursor})
        return res.get("jobs", [])

    async def get_job(self, job_id: str) -> dict[str, Any]:
        return await self._call("get_job", {"job_id": job_id})

    async def get_client_history(self, client_id: str) -> dict[str, Any]:
        return await self._call("get_client_history", {"client_id": client_id})

    async def get_connects_balance(self) -> dict[str, Any]:
        return await self._call("get_connects_balance", {})

    async def get_market_stats(self, category: str | None = None,
                               skills: list[str] | None = None) -> dict[str, Any]:
        return await self._call("get_market_stats", {"category": category, "skills": skills})

    async def get_platform_policy(self) -> dict[str, Any]:
        return await self._call("get_platform_policy", {})

    async def list_messages(self, thread_id: str | None = None) -> dict[str, Any]:
        return await self._call("list_messages", {"thread_id": thread_id})

    async def list_events(self, since: str | None = None) -> list[dict[str, Any]]:
        return (await self._call("list_events", {"since": since})).get("events", [])

    # ---- writes
    async def create_proposal_draft(self, payload: dict[str, Any], idempotency_key: str,
                                    dry_run: bool = False) -> dict[str, Any]:
        args = {k: payload.get(k) for k in ("job_id", "cover_letter", "screening_answers", "bid_amount")}
        return await self._call("create_proposal_draft",
                                {**args, "idempotency_key": idempotency_key, "dry_run": dry_run})

    async def submit_proposal(self, proposal_id: str, idempotency_key: str,
                              dry_run: bool = False) -> dict[str, Any]:
        return await self._call("submit_proposal", {"proposal_id": proposal_id,
                                                    "idempotency_key": idempotency_key, "dry_run": dry_run})

    async def send_message(self, thread_id: str, body: str, idempotency_key: str,
                           dry_run: bool = False) -> dict[str, Any]:
        return await self._call("send_message", {"thread_id": thread_id, "body": body,
                                                 "idempotency_key": idempotency_key, "dry_run": dry_run})
