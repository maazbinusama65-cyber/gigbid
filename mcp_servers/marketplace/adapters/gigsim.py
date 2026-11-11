"""GigSim adapter: REST (docs/INTERFACES.md section 2) -> adapter contract.

Auth is ``Authorization: Bearer $GIGSIM_API_TOKEN``; the acting freelancer is the ``X-Freelancer-Id``
header, so tenant scoping is enforced by GigSim as well as by this server.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from .base import AdapterError


class GigSimAdapter:
    name = "gigsim"

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
        retries: int = 2,
        backoff: float = 0.3,
    ) -> None:
        self.base_url = (base_url or os.getenv("GIGSIM_BASE_URL", "http://localhost:8081")).rstrip("/")
        self._token = token if token is not None else os.getenv("GIGSIM_API_TOKEN", "")
        self.retries, self.backoff = retries, backoff
        self._client = httpx.AsyncClient(base_url=self.base_url, transport=transport, timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ plumbing
    async def _request(self, method: str, path: str, user: str, *, params: dict | None = None,
                       json: dict | None = None, idem: str | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self._token}", "X-Freelancer-Id": user}
        if idem:
            # scoped by user so two tenants can never collide on the upstream dedupe table
            headers["Idempotency-Key"] = f"{user}:{idem}"
        attempt = 0
        while True:
            try:
                resp = await self._client.request(method, path, params=params, json=json, headers=headers)
            except httpx.HTTPError as exc:
                err = AdapterError("upstream_unavailable", f"GigSim unreachable: {type(exc).__name__}")
            else:
                if resp.status_code < 400:
                    return resp.json() if resp.content else {}
                err = self._map_error(resp)
            # Safe to retry writes too: the same Idempotency-Key makes them idempotent upstream.
            if err.code in ("upstream_unavailable", "upstream_rate_limited") and attempt < self.retries:
                attempt += 1
                await asyncio.sleep(min(err.retry_after or self.backoff * 2 ** (attempt - 1), 5.0))
                continue
            raise err

    @staticmethod
    def _map_error(resp: httpx.Response) -> AdapterError:
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("error") or resp.text[:200]
        except ValueError:
            detail = resp.text[:200]
        s = resp.status_code
        if s == 429:
            ra = resp.headers.get("Retry-After")
            return AdapterError("upstream_rate_limited", str(detail), float(ra) if ra else None)
        if s == 404:
            return AdapterError("not_found", str(detail))
        if s in (401, 403):
            return AdapterError("unauthorized", str(detail))
        if s >= 500:
            return AdapterError("upstream_unavailable", f"GigSim {s}: {detail}")
        return AdapterError("upstream_rejected", f"GigSim {s}: {detail}")

    # ------------------------------------------------------------------ reads
    async def search_jobs(self, user, *, q=None, category=None, skills=None, since=None,
                          limit=20, cursor=None):
        params = {"q": q, "category": category, "skills": ",".join(skills) if skills else None,
                  "since": since, "limit": limit, "cursor": cursor}
        return await self._request("GET", "/v1/jobs", user,
                                   params={k: v for k, v in params.items() if v is not None})

    async def get_job(self, user, job_id):
        return await self._request("GET", f"/v1/jobs/{job_id}", user)

    async def get_client(self, user, client_id):
        return await self._request("GET", f"/v1/clients/{client_id}", user)

    async def get_connects(self, user):
        return await self._request("GET", "/v1/connects", user)

    async def get_market_stats(self, user, category=None, skills=None):
        params = {"category": category, "skills": ",".join(skills) if skills else None}
        return await self._request("GET", "/v1/market_stats", user,
                                   params={k: v for k, v in params.items() if v is not None})

    async def get_policy(self, user):
        return await self._request("GET", "/v1/policy", user)

    async def list_messages(self, user, thread_id=None):
        if thread_id:
            body = await self._request("GET", "/v1/messages", user, params={"thread_id": thread_id})
            return {"thread_id": thread_id, "messages": _as_list(body, "messages")}
        return {"threads": _as_list(await self._request("GET", "/v1/threads", user), "threads")}

    async def list_events(self, user, since=None):
        body = await self._request("GET", "/v1/events", user,
                                   params={"since": since} if since else None)
        return _as_list(body, "events")

    async def get_proposal(self, user, proposal_id):
        return await self._request("GET", f"/v1/proposals/{proposal_id}", user)

    # ------------------------------------------------------------------ writes
    async def create_proposal(self, user, payload, idempotency_key, dry_run):
        body = {**payload, "dry_run": dry_run}
        return await self._request("POST", "/v1/proposals", user, json=body, idem=idempotency_key)

    async def submit_proposal(self, user, proposal_id, idempotency_key):
        return await self._request("POST", f"/v1/proposals/{proposal_id}/submit", user,
                                   json={}, idem=idempotency_key)

    async def send_message(self, user, thread_id, body, idempotency_key):
        return await self._request("POST", "/v1/messages", user,
                                   json={"thread_id": thread_id, "body": body}, idem=idempotency_key)


def _as_list(body: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return list(body.get(key) or [])
    return []
