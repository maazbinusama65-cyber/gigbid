from __future__ import annotations

import asyncio

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.common.audit import verify_chain
from mcp_servers.common.http_app import build_http_app
from mcp_servers.marketplace import build_server
from mcp_servers.marketplace.adapters.base import AdapterError
from mcp_servers.marketplace.service import MarketplaceConfig

from .fakes import FakeMarketplace

pytestmark = pytest.mark.asyncio

READS = {"search_jobs", "get_job", "get_client_history", "get_connects_balance", "list_messages",
         "list_events", "get_market_stats", "get_platform_policy"}
WRITES = {"create_proposal_draft", "submit_proposal", "send_message"}
LETTER = "I built a churn model with scikit-learn and would love to help you ship yours."


def key(n: str) -> str:
    return f"test-key-{n}"


async def call(c, name, args, meta=None):
    return await c.call_tool(name, args, meta=meta)


# ------------------------------------------------------------------ schemas / annotations
async def test_tool_inventory_annotations_and_schemas(server):
    async with connect(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == READS | WRITES
    for n in READS:
        a = tools[n].annotations
        assert a.readOnlyHint is True and a.destructiveHint is False and a.idempotentHint is True
        assert a.openWorldHint is True
    for n in WRITES:
        a = tools[n].annotations
        assert a.readOnlyHint is False and a.idempotentHint is True
        assert "idempotency_key" in tools[n].inputSchema["required"]
        assert "dry_run" in tools[n].inputSchema["properties"]
    assert tools["create_proposal_draft"].annotations.destructiveHint is False
    assert tools["submit_proposal"].annotations.destructiveHint is True
    assert tools["send_message"].annotations.destructiveHint is True
    assert all(t.outputSchema for t in tools.values())
    props = tools["create_proposal_draft"].inputSchema["properties"]
    assert props["bid_amount"]["exclusiveMinimum"] == 0 and props["bid_amount"]["maximum"] == 1_000_000
    assert props["cover_letter"]["minLength"] == 20 and props["cover_letter"]["maxLength"] == 5000
    assert "user_id" not in props  # tenant comes from the transport, never from the model


@pytest.mark.parametrize("args", [
    {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 100},                        # no key
    {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 100, "idempotency_key": "short"},
    {"job_id": "job-1", "cover_letter": "too short", "bid_amount": 100, "idempotency_key": key("a")},
    {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 0, "idempotency_key": key("a")},
    {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 10**9, "idempotency_key": key("a")},
    {"job_id": "../x", "cover_letter": LETTER, "bid_amount": 100, "idempotency_key": key("a")},
    {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 100, "idempotency_key": key("a"),
     "screening_answers": ["x"] * 11},
])
async def test_write_input_validation_rejects(server, fake, args):
    async with connect(server) as c:
        r = await call(c, "create_proposal_draft", args)
    assert r.isError
    assert fake.calls["create_proposal"] == 0


# ------------------------------------------------------------------ reads
async def test_read_tools_return_structured_output(server):
    async with connect(server) as c:
        jobs = await call(c, "search_jobs", {"query": "churn", "skills": ["Python"], "limit": 5})
        assert [j["job_id"] for j in jobs.structuredContent["jobs"]] == ["job-1"]
        job = await call(c, "get_job", {"job_id": "job-1"})
        assert job.structuredContent["budget"]["max"] == 500
        cl = await call(c, "get_client_history", {"client_id": "cl-1"})
        assert cl.structuredContent["history"][0]["outcome"] == "hired"
        bal = await call(c, "get_connects_balance", {})
        assert bal.structuredContent["balance"] == 100
        st = await call(c, "get_market_stats", {"category": "ml"})
        assert st.structuredContent["p50"] == 350 and st.structuredContent["n"] == 40
        pol = await call(c, "get_platform_policy", {})
        assert pol.structuredContent["connects_per_proposal"] == 8
        assert pol.structuredContent["rules"][0]["id"] == "no-offsite"
        th = await call(c, "list_messages", {})
        assert th.structuredContent["threads"][0]["thread_id"] == "t1"
        ev = await call(c, "list_events", {})
        assert ev.structuredContent["last_event_id"] == 2


async def test_upstream_not_found_is_clean_error(server):
    async with connect(server) as c:
        r = await call(c, "get_job", {"job_id": "nope"})
    assert r.isError and "not_found" in r.content[0].text


async def test_upstream_rate_limit_error_carries_retry_after(server, fake):
    fake.fail_next = AdapterError("upstream_rate_limited", "slow down", retry_after=2.0)
    async with connect(server) as c:
        r = await call(c, "get_connects_balance", {})
    assert r.isError and "upstream_rate_limited" in r.content[0].text and "retry after 2.0s" in r.content[0].text


# ------------------------------------------------------------------ dry run
async def test_dry_run_returns_exact_payload_and_cost_and_creates_nothing(server, fake):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 450.0,
            "screening_answers": ["By PR-AUC."], "idempotency_key": key("dry")}
    async with connect(server) as c:
        r = await call(c, "create_proposal_draft", {**args, "dry_run": True})
    s = r.structuredContent
    assert s["dry_run"] is True and s["status"] == "preview" and s["proposal_id"] is None
    assert s["connects_cost"] == 8 and s["balance_after"] == 92
    assert s["payload"] == {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 450.0,
                            "screening_answers": ["By PR-AUC."]}
    assert fake.proposals == {}


async def test_dry_run_does_not_burn_the_idempotency_key(server, fake):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 450.0, "idempotency_key": key("k1")}
    async with connect(server) as c:
        await call(c, "create_proposal_draft", {**args, "dry_run": True})
        real = await call(c, "create_proposal_draft", args)
    assert real.structuredContent["status"] == "draft" and len(fake.proposals) == 1


async def test_submit_dry_run_previews_cost_without_spending(server, fake):
    async with connect(server) as c:
        d = await call(c, "create_proposal_draft", {"job_id": "job-1", "cover_letter": LETTER,
                                                    "bid_amount": 300, "idempotency_key": key("c")})
        pid = d.structuredContent["proposal_id"]
        r = await call(c, "submit_proposal", {"proposal_id": pid, "idempotency_key": key("s"), "dry_run": True})
    s = r.structuredContent
    assert s["status"] == "preview" and s["connects_cost"] == 8 and s["balance_after"] == 92
    assert fake.balances.get("alice", 100) == 100 and fake.proposals[pid]["status"] == "draft"


async def test_submit_dry_run_flags_insufficient_connects(server, fake):
    fake.default_balance = 3
    async with connect(server) as c:
        d = await call(c, "create_proposal_draft", {"job_id": "job-1", "cover_letter": LETTER,
                                                    "bid_amount": 300, "idempotency_key": key("c")})
        r = await call(c, "submit_proposal", {"proposal_id": d.structuredContent["proposal_id"],
                                              "idempotency_key": key("s"), "dry_run": True})
    assert r.isError and "insufficient_connects" in r.content[0].text


async def test_send_message_dry_run(server, fake):
    async with connect(server) as c:
        r = await call(c, "send_message", {"thread_id": "t1", "body": "Hello", "idempotency_key": key("m"),
                                           "dry_run": True})
    assert r.structuredContent["status"] == "preview" and fake.messages == []


# ------------------------------------------------------------------ idempotency
async def test_create_retry_with_same_key_creates_one_draft(server, fake):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": key("c1")}
    async with connect(server) as c:
        a = await call(c, "create_proposal_draft", args)
        b = await call(c, "create_proposal_draft", args)
    assert a.structuredContent["proposal_id"] == b.structuredContent["proposal_id"]
    assert a.structuredContent["idempotent_replay"] is False
    assert b.structuredContent["idempotent_replay"] is True
    assert fake.calls["create_proposal"] == 1 and len(fake.proposals) == 1


async def test_same_key_different_arguments_is_conflict(server, fake):
    base = {"job_id": "job-1", "cover_letter": LETTER, "idempotency_key": key("c2")}
    async with connect(server) as c:
        await call(c, "create_proposal_draft", {**base, "bid_amount": 300})
        r = await call(c, "create_proposal_draft", {**base, "bid_amount": 999})
    assert r.isError and "idempotency_conflict" in r.content[0].text
    assert fake.calls["create_proposal"] == 1


async def test_submit_retry_never_spends_twice(server, fake):
    async with connect(server) as c:
        d = await call(c, "create_proposal_draft", {"job_id": "job-1", "cover_letter": LETTER,
                                                    "bid_amount": 300, "idempotency_key": key("c3")})
        sub = {"proposal_id": d.structuredContent["proposal_id"], "idempotency_key": key("s3")}
        first = await call(c, "submit_proposal", sub)
        second = await call(c, "submit_proposal", sub)
    assert first.structuredContent["status"] == "submitted"
    assert first.structuredContent["connects_cost"] == 8 and first.structuredContent["balance_after"] == 92
    assert second.structuredContent["idempotent_replay"] is True
    assert fake.calls["submit_proposal"] == 1 and fake.balances["alice"] == 92


async def test_idempotency_survives_process_restart(cfg, fake, tmp_path):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": key("r1")}
    async with connect(build_server(cfg)) as c:
        first = await call(c, "create_proposal_draft", args)
    # "restart": brand-new server + service + adapter, same state dir
    fake2 = FakeMarketplace()
    cfg2 = MarketplaceConfig(adapter=fake2, state_dir=cfg.state_dir, default_user="alice",
                             rate_limit_rpm=600, rate_burst=100)
    async with connect(build_server(cfg2)) as c:
        again = await call(c, "create_proposal_draft", args)
    assert again.structuredContent["proposal_id"] == first.structuredContent["proposal_id"]
    assert again.structuredContent["idempotent_replay"] is True
    assert fake2.calls["create_proposal"] == 0


async def test_concurrent_duplicates_execute_once(server, fake):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": key("cc")}
    async with connect(server) as c:
        rs = await asyncio.gather(*[call(c, "create_proposal_draft", args) for _ in range(4)])
    assert len({r.structuredContent["proposal_id"] for r in rs}) == 1
    assert fake.calls["create_proposal"] == 1


async def test_send_message_idempotent(server, fake):
    args = {"thread_id": "t1", "body": "Happy to start Monday.", "idempotency_key": key("m1")}
    async with connect(server) as c:
        a = await call(c, "send_message", args)
        b = await call(c, "send_message", args)
    assert a.structuredContent["message_id"] == b.structuredContent["message_id"]
    assert len(fake.messages) == 1


# ------------------------------------------------------------------ tenants
async def test_user_comes_from_meta_and_is_forwarded_to_adapter(server, fake):
    async with connect(server) as c:
        await call(c, "get_connects_balance", {}, meta={"user_id": "bob"})
        await call(c, "get_connects_balance", {})
    assert fake.users_seen == ["bob", "alice"]


async def test_invalid_user_id_rejected(server, fake):
    async with connect(server) as c:
        r = await call(c, "get_connects_balance", {}, meta={"user_id": "bob; DROP"})
    assert r.isError and "unauthorized" in r.content[0].text and fake.calls["get_connects"] == 0


async def test_cannot_submit_another_users_draft(server, fake):
    async with connect(server) as c:
        d = await call(c, "create_proposal_draft", {"job_id": "job-1", "cover_letter": LETTER,
                                                    "bid_amount": 300, "idempotency_key": key("o1")},
                       meta={"user_id": "alice"})
        r = await call(c, "submit_proposal", {"proposal_id": d.structuredContent["proposal_id"],
                                              "idempotency_key": key("o2")}, meta={"user_id": "mallory"})
    assert r.isError and "forbidden" in r.content[0].text
    assert fake.calls["submit_proposal"] == 0


async def test_same_key_different_users_do_not_collide(server, fake):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": key("x")}
    async with connect(server) as c:
        a = await call(c, "create_proposal_draft", args, meta={"user_id": "alice"})
        b = await call(c, "create_proposal_draft", args, meta={"user_id": "bob"})
    assert a.structuredContent["proposal_id"] != b.structuredContent["proposal_id"]


# ------------------------------------------------------------------ rate limit
async def test_rate_limit_per_user_with_refill(tmp_path, fake, clock):
    cfg = MarketplaceConfig(adapter=fake, state_dir=tmp_path, rate_limit_rpm=60, rate_burst=3, clock=clock)
    async with connect(build_server(cfg)) as c:
        ok = [await call(c, "get_connects_balance", {}, meta={"user_id": "u1"}) for _ in range(3)]
        assert not any(r.isError for r in ok)
        blocked = await call(c, "get_connects_balance", {}, meta={"user_id": "u1"})
        assert blocked.isError and "rate_limited" in blocked.content[0].text
        other = await call(c, "get_connects_balance", {}, meta={"user_id": "u2"})
        assert not other.isError  # buckets are per user
        clock.t += 2.0  # 60 rpm = 1 token / second
        assert not (await call(c, "get_connects_balance", {}, meta={"user_id": "u1"})).isError
    assert fake.calls["get_connects"] == 5  # the blocked call never reached the marketplace


async def test_default_rate_limit_is_below_gigsim_default():
    from mcp_servers.marketplace.service import DEFAULT_RPM

    assert DEFAULT_RPM < 60


# ------------------------------------------------------------------ audit log
async def test_audit_log_masks_pii_records_trace_and_chains(server, cfg):
    async with connect(server) as c:
        await call(c, "send_message", {"thread_id": "t1", "idempotency_key": key("au1"),
                                       "body": "Mail me at jane.doe@example.com or +44 7700 900123 please"},
                   meta={"user_id": "carol", "trace_id": "trace-42"})
        await call(c, "get_job", {"job_id": "nope"}, meta={"user_id": "carol"})
    path = cfg.resolved_audit_path()
    entries = [__import__("json").loads(x) for x in path.read_text().splitlines()]
    assert [e["tool"] for e in entries] == ["send_message", "get_job"]
    e = entries[0]
    assert e["user"] == "carol" and e["trace_id"] == "trace-42" and e["ok"] is True
    assert "jane.doe@example.com" not in path.read_text() and "7700" not in path.read_text()
    assert "[email]" in e["arguments"]["body"] and "[phone]" in e["arguments"]["body"]
    assert e["arguments"]["idempotency_key"] == key("au1")
    assert entries[1]["ok"] is False and "not_found" in entries[1]["result"]
    assert verify_chain(path)
    # tampering is detectable
    path.write_text(path.read_text().replace("carol", "mallory", 1))
    assert not verify_chain(path)


async def test_trace_id_argument_is_accepted(server, cfg):
    async with connect(server) as c:
        await call(c, "get_connects_balance", {"trace_id": "arg-trace"})
    assert cfg.resolved_audit_path().read_text().count('"trace_id": "arg-trace"') == 1


# ------------------------------------------------------------------ HTTP bearer auth
async def test_http_endpoint_requires_bearer_token(server):
    app = build_http_app(server, "s3cret-token-123")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9102") as h:
        body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
        hdr = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
        none = await h.post("/mcp", json=body, headers=hdr)
        wrong = await h.post("/mcp", json=body, headers={**hdr, "Authorization": "Bearer nope-nope-nope"})
        prefix = await h.post("/mcp", json=body, headers={**hdr, "Authorization": "Bearer s3cret-token-12"})
        scheme = await h.post("/mcp", json=body, headers={**hdr, "Authorization": "Basic s3cret-token-123"})
        health = await h.get("/health")
        async with app.router.lifespan_context(app):
            good = await h.post("/mcp", json=body, headers={**hdr, "Authorization": "Bearer s3cret-token-123"})
    assert none.status_code == wrong.status_code == prefix.status_code == scheme.status_code == 401
    assert none.headers["www-authenticate"] == "Bearer"
    assert health.status_code == 200
    assert good.status_code == 200 and "gigbid-marketplace" in good.text


async def test_bearer_middleware_rejects_empty_or_weak_token(server):
    with pytest.raises(ValueError):
        build_http_app(server, "")
    with pytest.raises(ValueError):
        build_http_app(server, "short")
