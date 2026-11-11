"""Marketplace MCP server over the REAL GigSim app (ASGI transport, no sockets)."""
from __future__ import annotations

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.marketplace import build_server
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.marketplace.service import MarketplaceConfig

gigsim_app = pytest.importorskip("gigsim.app")
from gigsim.settings import Settings  # noqa: E402

COVER = ("Your project needs a reproducible baseline and clear evaluation. I have shipped similar "
         "work before and can start this week with a short plan and weekly demos.")


@pytest.fixture()
def stack(tmp_path):
    app = gigsim_app.create_app(Settings(token="tok", state_path="", rate_limit_rpm=100000))
    adapter = GigSimAdapter("http://gigsim", "tok", transport=httpx.ASGITransport(app=app), backoff=0)
    cfg = MarketplaceConfig(adapter=adapter, state_dir=tmp_path / "state", default_user="ai_ml",
                            rate_limit_rpm=6000, rate_burst=500)
    return app, cfg


async def test_reads_and_policy_against_real_gigsim(stack):
    app, cfg = stack
    async with connect(build_server(cfg)) as c:
        jobs = (await c.call_tool("search_jobs", {"limit": 5})).structuredContent["jobs"]
        assert jobs and jobs[0]["budget"] is not None
        job = (await c.call_tool("get_job", {"job_id": jobs[0]["job_id"]})).structuredContent
        client = (await c.call_tool("get_client_history", {"client_id": job["client_id"]})).structuredContent
        assert client["client_id"] == job["client_id"]
        bal = (await c.call_tool("get_connects_balance", {})).structuredContent
        stats = (await c.call_tool("get_market_stats", {})).structuredContent
        pol = (await c.call_tool("get_platform_policy", {})).structuredContent
        missing = await c.call_tool("get_job", {"job_id": "does-not-exist"})
    assert bal["balance"] > 0 and stats["p50"] > 0 and stats["n"] > 0
    assert pol["connects_per_proposal"] == 8 and {r["id"] for r in pol["rules"]} >= {"R1", "R2"}
    assert missing.isError and "not_found" in missing.content[0].text


async def test_draft_submit_spends_connects_exactly_once(stack):
    app, cfg = stack
    async with connect(build_server(cfg)) as c:
        job = (await c.call_tool("search_jobs", {"limit": 1})).structuredContent["jobs"][0]
        before = (await c.call_tool("get_connects_balance", {})).structuredContent["balance"]
        args = {"job_id": job["job_id"], "cover_letter": COVER, "bid_amount": 300, "idempotency_key": "it-draft-0001"}
        prev = (await c.call_tool("create_proposal_draft", {**args, "dry_run": True})).structuredContent
        assert prev["status"] == "preview" and prev["proposal_id"] is None
        assert prev["connects_cost"] == job["connects_cost"] and prev["balance_after"] == before - prev["connects_cost"]
        assert (await c.call_tool("get_connects_balance", {})).structuredContent["balance"] == before  # nothing spent
        d1 = (await c.call_tool("create_proposal_draft", args)).structuredContent
        d2 = (await c.call_tool("create_proposal_draft", args)).structuredContent
        assert d1["status"] == "draft" and d1["proposal_id"] == d2["proposal_id"] and d2["idempotent_replay"]
        sub = {"proposal_id": d1["proposal_id"], "idempotency_key": "it-submit-0001"}
        s1 = (await c.call_tool("submit_proposal", sub)).structuredContent
        s2 = (await c.call_tool("submit_proposal", sub)).structuredContent
        after = (await c.call_tool("get_connects_balance", {})).structuredContent["balance"]
    assert s1["status"] == "submitted" and s1["connects_spent"] == prev["connects_cost"]
    assert s1["balance"] == before - prev["connects_cost"] == after   # spent once
    assert s2["idempotent_replay"] is True


async def test_server_restart_cannot_double_spend(stack, tmp_path):
    app, cfg = stack
    async with connect(build_server(cfg)) as c:
        job = (await c.call_tool("search_jobs", {"limit": 1})).structuredContent["jobs"][0]
        d = (await c.call_tool("create_proposal_draft", {
            "job_id": job["job_id"], "cover_letter": COVER, "bid_amount": 200,
            "idempotency_key": "it-restart-draft"})).structuredContent
        sub = {"proposal_id": d["proposal_id"], "idempotency_key": "it-restart-sub1"}
        await c.call_tool("submit_proposal", sub)
    cfg2 = MarketplaceConfig(adapter=cfg.adapter, state_dir=cfg.state_dir, default_user="ai_ml",
                             rate_limit_rpm=6000, rate_burst=500)
    async with connect(build_server(cfg2)) as c:
        again = (await c.call_tool("submit_proposal", sub)).structuredContent
        bal = (await c.call_tool("get_connects_balance", {})).structuredContent
    assert again["idempotent_replay"] is True and bal["spent_this_week"] == job["connects_cost"]


async def test_tenants_see_separate_connects(stack):
    app, cfg = stack
    async with connect(build_server(cfg)) as c:
        job = (await c.call_tool("search_jobs", {"limit": 1})).structuredContent["jobs"][0]
        d = (await c.call_tool("create_proposal_draft", {
            "job_id": job["job_id"], "cover_letter": COVER, "bid_amount": 200,
            "idempotency_key": "it-tenant-draft"}, meta={"user_id": "ai_ml"})).structuredContent
        await c.call_tool("submit_proposal", {"proposal_id": d["proposal_id"], "idempotency_key": "it-tenant-sub1"},
                          meta={"user_id": "ai_ml"})
        other = (await c.call_tool("get_connects_balance", {}, meta={"user_id": "fullstack"})).structuredContent
        mine = (await c.call_tool("get_connects_balance", {}, meta={"user_id": "ai_ml"})).structuredContent
    assert other["spent_this_week"] == 0 and mine["spent_this_week"] > 0


async def test_messages_after_simulated_time(stack):
    app, cfg = stack
    transport = httpx.ASGITransport(app=app)
    thread_id = None
    async with connect(build_server(cfg)) as c:
        jobs = (await c.call_tool("search_jobs", {"limit": 12})).structuredContent["jobs"]
        for i, j in enumerate(jobs):  # evidence-specific letters + sensible price raise reply odds
            letter = (f"For your {j['title']} project I have delivered {', '.join(j['required_skills'])} work for "
                      f"similar clients with measurable results and weekly demos. I would start with "
                      f"{j['required_skills'][0]} this week.")
            d = (await c.call_tool("create_proposal_draft", {
                "job_id": j["job_id"], "cover_letter": letter, "bid_amount": (j["budget"] or {}).get("min") or 100,
                "idempotency_key": f"it-msg-draft-{i:02d}"})).structuredContent
            await c.call_tool("submit_proposal", {"proposal_id": d["proposal_id"], "idempotency_key": f"it-msg-sub-{i:02d}"})
        async with httpx.AsyncClient(transport=transport, base_url="http://gigsim",
                                     headers={"Authorization": "Bearer tok", "X-Freelancer-Id": "ai_ml"}) as raw:
            await raw.post("/v1/sim/tick", json={"steps": 24 * 30})
        events = (await c.call_tool("list_events", {})).structuredContent
        assert events["events"] and events["last_event_id"] is not None
        threads = (await c.call_tool("list_messages", {})).structuredContent["threads"]
        if threads:
            thread_id = threads[0]["thread_id"]
            args = {"thread_id": thread_id, "body": "Thanks for the reply, happy to proceed.",
                    "idempotency_key": "it-msg-send-1"}
            a = (await c.call_tool("send_message", args)).structuredContent
            b = (await c.call_tool("send_message", args)).structuredContent
            msgs = (await c.call_tool("list_messages", {"thread_id": thread_id})).structuredContent["messages"]
    if thread_id is None:
        pytest.skip("this GigSim seed produced no client reply thread; send_message path not exercised")
    assert a["status"] == "sent" and b["idempotent_replay"]
    assert sum(1 for m in msgs if m.get("body") == args["body"]) == 1
