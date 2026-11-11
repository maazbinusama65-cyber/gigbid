from __future__ import annotations

import json

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.marketplace import build_server
from mcp_servers.marketplace.adapters.base import AdapterError
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.marketplace.service import MarketplaceConfig


def make(handler, **kw):
    return GigSimAdapter("http://gigsim", "tok-123", transport=httpx.MockTransport(handler), backoff=0, **kw)


async def test_headers_params_and_user_scoping():
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200, json={"jobs": [], "next_cursor": None})

    a = make(handler)
    await a.search_jobs("ai_ml", q="rag", category="ml", skills=["Python", "SQL"], limit=5)
    r = seen[0]
    assert r.headers["authorization"] == "Bearer tok-123" and r.headers["x-freelancer-id"] == "ai_ml"
    assert dict(r.url.params) == {"q": "rag", "category": "ml", "skills": "Python,SQL", "limit": "5"}


async def test_create_proposal_forwards_dry_run_and_scoped_idempotency_key():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json={"proposal_id": None, "status": "preview", "connects_cost": 8,
                                         "balance_after": 92, "payload": {}})

    a = make(handler)
    await a.create_proposal("ai_ml", {"job_id": "j1", "cover_letter": "x", "screening_answers": [],
                                      "bid_amount": 10}, "key-12345678", True)
    assert json.loads(seen[0].content)["dry_run"] is True
    assert seen[0].headers["idempotency-key"] == "ai_ml:key-12345678"
    assert seen[0].url.path == "/v1/proposals"


async def test_error_mapping():
    def handler(req):
        return {"/v1/jobs/missing": httpx.Response(404, json={"error": "not_found", "detail": "no job"}),
                "/v1/connects": httpx.Response(401, json={"error": "unauthorized"}),
                "/v1/policy": httpx.Response(422, json={"error": "bad", "detail": "nope"})}[req.url.path]

    a = make(handler)
    for call, code in [(a.get_job("u", "missing"), "not_found"), (a.get_connects("u"), "unauthorized"),
                       (a.get_policy("u"), "upstream_rejected")]:
        with pytest.raises(AdapterError) as e:
            await call
        assert e.value.code == code


async def test_retries_429_then_succeeds_and_gives_up_on_persistent_5xx():
    n = {"c": 0}

    def flaky(req):
        n["c"] += 1
        if n["c"] < 3:
            return httpx.Response(429, json={"error": "rate"}, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"balance": 5})

    assert (await make(flaky).get_connects("u"))["balance"] == 5 and n["c"] == 3

    m = {"c": 0}

    def down(req):
        m["c"] += 1
        return httpx.Response(503, json={"error": "down"})

    with pytest.raises(AdapterError) as e:
        await make(down).get_connects("u")
    assert e.value.code == "upstream_unavailable" and m["c"] == 3  # 1 try + 2 retries


async def test_connection_error_maps_to_unavailable():
    def boom(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(AdapterError) as e:
        await make(boom).get_connects("u")
    assert e.value.code == "upstream_unavailable"


async def test_full_stack_mcp_server_over_gigsim_adapter(tmp_path):
    """MCP tool -> guards -> GigSimAdapter -> (mock) REST."""
    sent = []

    def handler(req):
        sent.append((req.method, req.url.path))
        if req.url.path == "/v1/proposals":
            return httpx.Response(200, json={"proposal_id": "P9", "status": "draft", "connects_cost": 8,
                                             "balance_after": 92, "payload": {"job_id": "j1"}})
        if req.url.path == "/v1/market_stats":
            return httpx.Response(200, json={"n": 10, "p50": 200})
        return httpx.Response(404, json={"error": "nf"})

    cfg = MarketplaceConfig(adapter=make(handler), state_dir=tmp_path, default_user="ai_ml")
    async with connect(build_server(cfg)) as c:
        r = await c.call_tool("create_proposal_draft", {
            "job_id": "j1", "cover_letter": "A cover letter long enough to pass.", "bid_amount": 120,
            "idempotency_key": "run1:j1:draft"})
        s = await c.call_tool("get_market_stats", {"category": "ml"})
    assert r.structuredContent["proposal_id"] == "P9" and r.structuredContent["status"] == "draft"
    assert s.structuredContent["p50"] == 200 and ("GET", "/v1/market_stats") in sent


async def test_integration_against_real_gigsim_app_if_present(tmp_path):
    pytest.importorskip("gigsim.app")
    from gigsim.app import app  # type: ignore[import-not-found]

    transport = httpx.ASGITransport(app=app)
    adapter = GigSimAdapter("http://gigsim", "dev-token", transport=transport, backoff=0)
    try:
        health = await adapter._client.get("/health")
        assert health.status_code == 200
        bal = await adapter.get_connects("ai_ml")
        assert "balance" in bal
    except AdapterError as exc:  # token mismatch etc. should surface as a clean adapter error
        assert exc.code in {"unauthorized", "upstream_unavailable"}
    finally:
        await adapter.aclose()
