"""Live adapter unit tests. NOTHING here talks to Upwork: a fake MCP session stands in for it."""
from __future__ import annotations

import base64
import hashlib
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.marketplace import build_server
from mcp_servers.marketplace.adapters.base import AdapterError
from mcp_servers.marketplace.adapters.upwork_live import UpworkLiveAdapter
from mcp_servers.marketplace.adapters.upwork_oauth import (
    AuthFlow,
    EncryptedTokenStore,
    OAuthConfig,
    OAuthError,
    TokenSet,
    build_authorization_url,
    discover_endpoints,
    generate_pkce,
    refresh_tokens,
)
from mcp_servers.marketplace.service import MarketplaceConfig

SECRET = "unit-test-secret-key-0123456789"


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        r = self.responses[name]
        if isinstance(r, Exception):
            raise r
        return NS(isError=False, structuredContent=r, content=[])

    async def list_tools(self):
        return NS(tools=[NS(name=n) for n in self.responses])


def make_adapter(tmp_path, responses, **kw):
    store = EncryptedTokenStore(tmp_path / "tok.json", SECRET)
    store.put("alice", TokenSet("access-AAA", "refresh-RRR", 9_999_999_999))
    sess = FakeSession(responses)
    tokens_seen = []

    @asynccontextmanager
    async def factory(user, token):
        tokens_seen.append(token)
        yield sess

    ad = UpworkLiveAdapter(token_store=store, session_factory=factory, connects_per_proposal=8, **kw)
    return ad, sess, tokens_seen


JOB = {"id": "u-1", "title": "T", "description": "D", "skills": ["Python"], "amount": 300,
       "connects_required": 12}
RESP = {"get_job": JOB, "get_connects_balance": {"balance": 50}, "search_jobs": {"jobs": [JOB]},
        "create_proposal_draft": {"draft_id": "d-77"}, "create_message_draft": {"id": "m-1"},
        "list_threads": [{"thread_id": "t1"}]}


# ------------------------------------------------------------------ mapping
async def test_reads_map_onto_port_shapes_and_use_user_token(tmp_path):
    ad, sess, tokens = make_adapter(tmp_path, RESP)
    jobs = await ad.search_jobs("alice", q="x", limit=5)
    assert jobs["jobs"][0]["job_id"] == "u-1" and jobs["jobs"][0]["budget"]["max"] == 300
    assert jobs["jobs"][0]["required_skills"] == ["Python"] and jobs["jobs"][0]["connects_cost"] == 12
    assert (await ad.get_connects("alice"))["balance"] == 50
    assert (await ad.list_messages("alice"))["threads"] == [{"thread_id": "t1"}]
    assert set(tokens) == {"access-AAA"}
    assert sess.calls[0] == ("search_jobs", {"query": "x", "limit": 5})  # None args dropped


async def test_reads_are_cached_to_avoid_scraping_like_patterns(tmp_path):
    t = {"now": 0.0}
    ad, sess, _ = make_adapter(tmp_path, RESP, read_cache_ttl=300, clock=lambda: t["now"])
    for _ in range(5):
        await ad.get_job("alice", "u-1")
    assert len(sess.calls) == 1
    t["now"] = 301
    await ad.get_job("alice", "u-1")
    assert len(sess.calls) == 2


async def test_unsupported_operations_are_documented_errors(tmp_path):
    ad, _, _ = make_adapter(tmp_path, RESP)
    for coro in (ad.get_market_stats("alice", "ml", None), ad.list_events("alice", None),
                 ad.get_proposal("alice", "p")):
        with pytest.raises(AdapterError) as e:
            await coro
        assert e.value.code == "unsupported"
    pol = await ad.get_policy("alice")
    assert pol["connects_per_proposal"] == 8 and pol["rules"] == []


# ------------------------------------------------------------------ drafts only
async def test_writes_only_create_drafts_and_never_submit(tmp_path):
    ad, sess, _ = make_adapter(tmp_path, RESP)
    payload = {"job_id": "u-1", "cover_letter": "x" * 30, "screening_answers": [], "bid_amount": 100}
    prev = await ad.create_proposal("alice", payload, "key-123456789", dry_run=True)
    assert prev["status"] == "preview" and prev["connects_cost"] == 12 and prev["balance_after"] == 38
    assert all(n != "create_proposal_draft" for n, _ in sess.calls)  # dry run never writes
    d = await ad.create_proposal("alice", payload, "key-123456789", dry_run=False)
    assert d["status"] == "draft" and d["proposal_id"] == "d-77" and d["requires_user_confirmation"]
    sub = await ad.submit_proposal("alice", "d-77", "key-sub-1234")
    assert sub["status"] == "draft" and sub["requires_user_confirmation"] is True
    msg = await ad.send_message("alice", "t1", "hello", "key-msg-1234")
    assert msg["status"] == "draft" and msg["requires_user_confirmation"]
    called = {n for n, _ in sess.calls}
    assert called <= {"get_job", "get_connects_balance", "create_proposal_draft", "create_message_draft"}
    assert not any("submit" in n or n == "send_message" for n in called)


async def test_through_mcp_server_live_mode_never_reports_submitted(tmp_path):
    ad, _, _ = make_adapter(tmp_path, RESP)
    cfg = MarketplaceConfig(adapter=ad, state_dir=tmp_path / "st", default_user="alice", mode="upwork_live")
    async with connect(build_server(cfg)) as c:
        d = await c.call_tool("create_proposal_draft", {"job_id": "u-1", "cover_letter": "y" * 40,
                                                        "bid_amount": 90, "idempotency_key": "k-live-0001"})
        s = await c.call_tool("submit_proposal", {"proposal_id": d.structuredContent["proposal_id"],
                                                  "idempotency_key": "k-live-0002"})
    assert s.structuredContent["status"] == "draft"
    assert s.structuredContent["requires_user_confirmation"] is True


async def test_custom_tool_map_and_discovery(tmp_path):
    ad, sess, _ = make_adapter(tmp_path, {"findJobs": {"jobs": []}, **RESP}, tool_map={"search_jobs": "findJobs"})
    await ad.search_jobs("alice", q="x")
    assert sess.calls[0][0] == "findJobs"
    assert "findJobs" in await ad.list_tools("alice")


async def test_transport_failure_maps_to_unavailable_without_leaking_token(tmp_path):
    ad, _, _ = make_adapter(tmp_path, {**RESP, "get_job": RuntimeError("boom access-AAA")})
    with pytest.raises(AdapterError) as e:
        await ad.get_job("alice", "u-1")
    assert e.value.code == "upstream_unavailable" and "access-AAA" not in str(e.value)


async def test_missing_or_unrefreshable_token_is_unauthorized(tmp_path):
    ad, _, _ = make_adapter(tmp_path, RESP)
    with pytest.raises(AdapterError) as e:
        await ad.get_connects("stranger")
    assert e.value.code == "unauthorized"
    ad.store.put("old", TokenSet("a", None, 1.0))  # expired, no oauth config
    with pytest.raises(AdapterError) as e2:
        await ad.get_connects("old")
    assert e2.value.code == "unauthorized"


# ------------------------------------------------------------------ OAuth helpers
def test_pkce_s256_challenge_matches_verifier():
    v, c = generate_pkce()
    assert 43 <= len(v) <= 128
    assert c == base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).rstrip(b"=").decode()
    assert generate_pkce()[0] != v


def test_authorization_url_has_pkce_state_and_resource():
    url = build_authorization_url("https://auth.example/authorize", "cid", "http://localhost/cb", "st",
                                  "chal", scope="read", resource="https://mcp.upwork.com/mcp")
    q = httpx.URL(url).params
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["state"] == "st" and q["code_challenge"] == "chal" and q["resource"].endswith("/mcp")


def test_token_store_encrypts_at_rest_and_rejects_weak_secret(tmp_path):
    store = EncryptedTokenStore(tmp_path / "t.json", SECRET)
    store.put("alice", TokenSet("SECRET-ACCESS", "SECRET-REFRESH", 123.0))
    raw = (tmp_path / "t.json").read_text()
    assert "SECRET-ACCESS" not in raw and "SECRET-REFRESH" not in raw and "alice" in raw
    assert store.get("alice").access_token == "SECRET-ACCESS"
    assert store.get("bob") is None
    with pytest.raises(OAuthError):
        EncryptedTokenStore(tmp_path / "x.json", "replace_me")
    with pytest.raises(OAuthError):  # wrong key cannot decrypt
        EncryptedTokenStore(tmp_path / "t.json", "another-secret-key-0123456789").get("alice")
    store.delete("alice")
    assert store.get("alice") is None


def test_tokenset_repr_hides_secrets():
    assert "SECRET" not in repr(TokenSet("SECRET-A", "SECRET-R", 1.0))


async def test_auth_flow_end_to_end_with_mock_server(tmp_path):
    posted = []

    def handler(req: httpx.Request):
        posted.append(dict(httpx.QueryParams(req.content.decode())))
        return httpx.Response(200, json={"access_token": "NEW-AT", "refresh_token": "NEW-RT", "expires_in": 3600})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = EncryptedTokenStore(tmp_path / "t.json", SECRET)
    flow = AuthFlow(OAuthConfig("cid", "https://a/authorize", "https://a/token", "http://localhost/cb"), store)
    url = flow.start("alice")
    state = httpx.URL(url).params["state"]
    assert await flow.complete(state, "the-code", http) == "alice"
    assert posted[0]["grant_type"] == "authorization_code" and posted[0]["code"] == "the-code"
    assert posted[0]["code_verifier"] and "client_secret" not in posted[0]
    assert store.get("alice").access_token == "NEW-AT"
    with pytest.raises(OAuthError):  # state is single-use
        await flow.complete(state, "the-code", http)
    with pytest.raises(OAuthError):
        await flow.complete("forged", "c", http)


async def test_refresh_expired_token_before_calling(tmp_path):
    def handler(req):
        body = dict(httpx.QueryParams(req.content.decode()))
        assert body["grant_type"] == "refresh_token" and body["refresh_token"] == "OLD-RT"
        return httpx.Response(200, json={"access_token": "FRESH", "expires_in": 3600})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    store = EncryptedTokenStore(tmp_path / "t.json", SECRET)
    store.put("alice", TokenSet("STALE", "OLD-RT", 1.0))
    sess = FakeSession(RESP)
    tokens = []

    @asynccontextmanager
    async def factory(user, token):
        tokens.append(token)
        yield sess

    ad = UpworkLiveAdapter(token_store=store, session_factory=factory, http=http,
                           oauth=OAuthConfig("cid", "x", "https://a/token", "http://localhost/cb"))
    await ad.get_connects("alice")
    assert tokens == ["FRESH"] and store.get("alice").refresh_token == "OLD-RT"  # refresh token retained


async def test_token_endpoint_error_does_not_leak(tmp_path):
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"error": "invalid_grant"})))
    with pytest.raises(OAuthError, match="invalid_grant"):
        await refresh_tokens("https://a/token", client_id="cid", tokens=TokenSet("a", "RT-SECRET", 1.0), http=http)


async def test_discovery_follows_rfc9728_then_rfc8414():
    def handler(req):
        if req.url.path == "/.well-known/oauth-protected-resource":
            return httpx.Response(200, json={"authorization_servers": ["https://auth.up.example"]})
        return httpx.Response(200, json={"authorization_endpoint": "https://auth.up.example/a",
                                         "token_endpoint": "https://auth.up.example/t"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ep = await discover_endpoints("https://mcp.upwork.com/mcp", http)
    assert ep["authorize"].endswith("/a") and ep["token"].endswith("/t")


async def test_tokens_never_logged(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    ad, _, _ = make_adapter(tmp_path, RESP)
    await ad.get_job("alice", "u-1")
    assert "access-AAA" not in caplog.text and "refresh-RRR" not in caplog.text
