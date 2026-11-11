"""ToolGateway: allowlists, retries/backoff, timeouts, degraded mode + queue/recover, trace, port."""
from __future__ import annotations

import asyncio

import pytest

from agent.marketplace_port import MarketplacePort, McpMarketplacePort
from agent.mcp_client import (
    AGENT_ALLOWLISTS,
    MARKETPLACE_READ,
    MARKETPLACE_WRITE,
    PORTFOLIO_READ,
    WORKSPACE_TOOLS,
    WRITE_TOOLS,
    allowed_tools,
    build_connections,
)
from agent.tools import (
    ApprovalRequired,
    ToolCallFailed,
    ToolGateway,
    ToolNotAllowed,
    ToolUnavailable,
)
from mcp_servers.marketplace import build_server as build_marketplace
from mcp_servers.marketplace.service import MarketplaceConfig
from mcp_servers.marketplace.tests.fakes import FakeMarketplace
from mcp_servers.portfolio import build_server as build_portfolio
from mcp_servers.portfolio.service import PortfolioConfig
from mcp_servers.portfolio.tests.data import make_portfolio
from mcp_servers.workspace import WorkspaceConfig
from mcp_servers.workspace import build_server as build_workspace

LETTER = "I built a churn model with scikit-learn and would love to help you ship yours."
ALL_TOOLS = MARKETPLACE_READ | MARKETPLACE_WRITE | PORTFOLIO_READ | WORKSPACE_TOOLS


class Clock:
    t = 100.0

    def __call__(self) -> float:
        return self.t


class Env:
    """Gateway over in-memory servers + handles to poke them."""

    def __init__(self, tmp_path, **gw_kw):
        self.fake = FakeMarketplace()
        self.mclock = Clock()
        self.clock = Clock()
        self.sleeps: list[float] = []
        mcfg = MarketplaceConfig(adapter=self.fake, state_dir=tmp_path / "m", default_user="alice",
                                 rate_limit_rpm=600, rate_burst=100, clock=self.mclock)
        root = make_portfolio(tmp_path / "personas")
        self.servers = {
            "marketplace": build_marketplace(mcfg),
            "portfolio": build_portfolio(PortfolioConfig(data_dir=str(root), default_portfolio_id="ai_ml",
                                                         backend="local")),
            "workspace": build_workspace(WorkspaceConfig(store_path=tmp_path / "w" / "s.json",
                                                         default_user="alice")),
        }
        cfg = {"tool_servers": {"transport": "memory", "timeout_seconds": 5, "retries": 3,
                                "backoff_seconds": 0.5, "cooldown_seconds": 10}}

        async def sleep(s):
            self.sleeps.append(s)

        self.gw = ToolGateway(cfg, user_id="alice", servers=self.servers, clock=self.clock, sleep=sleep, **gw_kw)

    def kill(self, name="marketplace"):
        self._saved = self.servers[name]
        self.servers[name] = None

    def revive(self, name="marketplace"):
        self.servers[name] = self._saved


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


# ------------------------------------------------------------------ allowlists
@pytest.mark.parametrize("agent", sorted(AGENT_ALLOWLISTS))
async def test_every_agent_can_call_exactly_its_allowlist(env, agent):
    allowed = {t for tools in allowed_tools(agent).values() for t in tools}
    for tool in sorted(ALL_TOOLS):
        if tool in allowed:
            continue
        with pytest.raises(ToolNotAllowed):
            await env.gw.call(agent, tool, {})
    assert not env.fake.calls  # nothing reached a server


def test_allowlist_matrix_matches_the_spec():
    a = {k: {t for ts in v.values() for t in ts} for k, v in AGENT_ALLOWLISTS.items()}
    assert a["analyst"] == set() and a["job_analyst"] == set()
    assert a["scout"] == {"search_jobs", "get_job"}
    assert a["risk_assessor"] == {"get_client_history", "get_job"}
    assert a["fit_matcher"] == PORTFOLIO_READ and a["writer"] == PORTFOLIO_READ and a["critic"] == PORTFOLIO_READ
    assert a["pricing"] == {"get_market_stats", "get_connects_balance", "get_job"}
    assert a["compliance"] == {"get_platform_policy"}
    assert a["submitter"] == {"create_proposal_draft", "submit_proposal"}
    assert a["client_liaison"] == MARKETPLACE_READ | {"send_message"} | WORKSPACE_TOOLS | {"search_evidence"}
    writers = {k for k, v in a.items() if v & WRITE_TOOLS}
    assert writers == {"submitter", "client_liaison"}


async def test_allowlists_only_name_tools_that_really_exist(env):
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    real: dict[str, set[str]] = {}
    for name, srv in env.servers.items():
        async with connect(srv) as c:
            real[name] = {t.name for t in (await c.list_tools()).tools}
    for agent, by_server in AGENT_ALLOWLISTS.items():
        for server, tools in by_server.items():
            if server in real:
                assert tools <= real[server], (agent, server, tools - real[server])


async def test_unknown_agent_and_unknown_tool_rejected(env):
    with pytest.raises(ToolNotAllowed):
        await env.gw.call("rogue", "get_job", {"job_id": "job-1"})
    with pytest.raises(ToolNotAllowed):
        await env.gw.call("scout", "delete_everything", {})


# ------------------------------------------------------------------ results + trace
async def test_call_returns_plain_dict_and_records_trace(env):
    res = await env.gw.call("scout", "search_jobs", {"query": "churn", "category": None, "limit": 5})
    assert type(res) is dict and res["jobs"][0]["job_id"] == "job-1"
    assert (await env.gw.call("scout", "get_job", {"job_id": "job-1"}))["connects_cost"] == 8
    rec = env.gw.trace[0]
    assert {"agent", "tool", "args", "result_digest", "latency_s", "ok", "trace_id"} <= set(rec)
    assert rec["agent"] == "scout" and rec["tool"] == "search_jobs" and rec["ok"] is True
    assert rec["latency_s"] >= 0 and "job-1" in rec["result_digest"] and rec["server"] == "marketplace"


async def test_trace_masks_pii_in_args_and_records_failures(env):
    with pytest.raises(ToolNotAllowed):
        await env.gw.call("scout", "send_message", {"body": "mail me jane@example.com"})
    await env.gw.call("client_liaison", "send_message", {
        "thread_id": "t1", "body": "reach me: jane.doe@example.com", "idempotency_key": "key-pii-0001"})
    assert env.gw.trace[0]["ok"] is False and "ToolNotAllowed" in env.gw.trace[0]["error"]
    assert "jane.doe@example.com" not in str(env.gw.trace[1]["args"])


async def test_for_run_shares_connections_and_attributes_records(env):
    a, b = env.gw.for_run("run-A"), env.gw.for_run("run-B")
    await a.call("scout", "get_job", {"job_id": "job-1"})
    await b.call("scout", "get_job", {"job_id": "job-2"})
    await a.call("pricing", "get_connects_balance", {})
    assert [r["tool"] for r in a.trace] == ["get_job", "get_connects_balance"]
    assert [r["args"] for r in b.trace] == [{"job_id": "job-2"}]
    assert len(env.gw.trace) == 3 and {r["trace_id"] for r in env.gw.trace} == {"run-A", "run-B"}
    env.kill()
    with pytest.raises(ToolUnavailable):
        await a.call("scout", "get_job", {"job_id": "job-1"})
    assert env.gw.status()["degraded"] == ["marketplace"]  # health is shared across views
    with pytest.raises(ToolUnavailable):
        await b.call("scout", "get_job", {"job_id": "job-1"})


async def test_trace_id_reaches_the_server_audit_log(env, tmp_path):
    await env.gw.for_run("trace-xyz").call("pricing", "get_connects_balance", {})
    audit = (tmp_path / "m" / "audit.jsonl").read_text()
    assert '"trace_id": "trace-xyz"' in audit and '"user": "alice"' in audit


async def test_user_id_is_forwarded_for_tenant_scoping(tmp_path):
    e = Env(tmp_path)
    bob = ToolGateway({"tool_servers": {}}, user_id="bob", servers=e.servers)
    await bob.call("pricing", "get_connects_balance", {})
    assert e.fake.users_seen == ["bob"]


# ------------------------------------------------------------------ tool-level errors
async def test_tool_errors_are_not_retried_and_do_not_degrade(env):
    with pytest.raises(ToolCallFailed) as e:
        await env.gw.call("scout", "get_job", {"job_id": "nope"})
    assert e.value.code == "not_found" and env.sleeps == []
    with pytest.raises(ToolCallFailed) as e2:
        await env.gw.call("submitter", "create_proposal_draft", {
            "job_id": "job-1", "cover_letter": "short", "bid_amount": 5, "idempotency_key": "key-valid-001"})
    assert e2.value.code == "invalid_arguments"
    assert env.gw.status()["ok"] is True


async def test_persistent_rate_limit_is_a_failure_not_an_outage(tmp_path):
    e = Env(tmp_path)
    e.servers["marketplace"] = build_marketplace(MarketplaceConfig(
        adapter=e.fake, state_dir=tmp_path / "rl", rate_limit_rpm=60, rate_burst=1, clock=e.mclock))
    await e.gw.call("pricing", "get_connects_balance", {})
    with pytest.raises(ToolCallFailed) as err:
        await e.gw.call("pricing", "get_connects_balance", {})
    assert err.value.code == "rate_limited" and e.gw.status()["ok"]
    assert e.sleeps  # it waited (server-advised retry-after) before giving up


# ------------------------------------------------------------------ retries / timeouts
async def test_retries_with_exponential_backoff_then_succeeds(env):
    real, n = env.gw._once, {"c": 0}

    async def flaky(*a, **k):
        n["c"] += 1
        if n["c"] <= 2:
            raise ConnectionError("blip")
        return await real(*a, **k)

    env.gw._once = flaky
    res = await env.gw.call("scout", "get_job", {"job_id": "job-1"})
    assert res["job_id"] == "job-1" and n["c"] == 3
    assert env.sleeps == [0.5, 1.0] and env.gw.trace[0]["attempts"] == 3
    assert env.gw.status()["ok"]


async def test_retries_are_bounded(env):
    n = {"c": 0}

    async def down(*a, **k):
        n["c"] += 1
        raise ConnectionError("refused")

    env.gw._once = down
    with pytest.raises(ToolUnavailable):
        await env.gw.call("scout", "get_job", {"job_id": "job-1"})
    assert n["c"] == 4 and env.sleeps == [0.5, 1.0, 2.0]  # 1 try + retries=3


async def test_timeout_per_attempt(tmp_path):
    e = Env(tmp_path)
    e.gw._shared.timeout = 0.05

    async def hang(*a, **k):
        await asyncio.sleep(10)

    e.gw._once = hang
    with pytest.raises(ToolUnavailable, match="timeout"):
        await e.gw.call("scout", "get_job", {"job_id": "job-1"})


# ------------------------------------------------------------------ degraded mode
async def test_killed_server_degrades_fast_fails_and_other_servers_keep_working(env):
    env.kill()
    with pytest.raises(ToolUnavailable) as e:
        await env.gw.call("scout", "get_job", {"job_id": "job-1"})
    assert e.value.server == "marketplace"
    st = env.gw.status()
    assert st["ok"] is False and st["degraded"] == ["marketplace"]
    assert "marketplace tools are unavailable" in st["message"]
    n = len(env.sleeps)
    with pytest.raises(ToolUnavailable, match="degraded"):  # circuit open: no new attempts
        await env.gw.call("scout", "get_job", {"job_id": "job-1"})
    assert len(env.sleeps) == n
    ok = await env.gw.call("fit_matcher", "list_skills", {})  # portfolio unaffected
    assert ok["skills"]


async def test_recovery_after_cooldown_without_manual_action(env):
    env.kill()
    with pytest.raises(ToolUnavailable):
        await env.gw.call("scout", "get_job", {"job_id": "job-1"})
    env.revive()
    env.clock.t += 11  # cooldown elapsed -> next call is the half-open probe
    assert (await env.gw.call("scout", "get_job", {"job_id": "job-1"}))["job_id"] == "job-1"
    st = env.gw.status()
    assert st["ok"] is True and st["message"] is None


async def test_writes_are_queued_while_down_and_replayed_once_on_recover(env):
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": "key-queue-0001"}
    env.kill()
    for _ in range(2):  # the caller retrying must not double-queue
        with pytest.raises(ToolUnavailable) as e:
            await env.gw.call("submitter", "create_proposal_draft", args)
        assert e.value.queued is True
    assert env.gw.status()["queued"] == 1
    assert "queued" in env.gw.status()["message"]
    assert (await env.gw.recover())["recovered"] == []  # still down: nothing replayed, queue kept
    assert env.gw.status()["queued"] == 1
    env.revive()
    out = await env.gw.recover()
    assert out["recovered"] == ["marketplace"] and len(out["replayed"]) == 1 and out["still_queued"] == 0
    assert out["replayed"][0]["result"]["status"] == "draft"
    assert env.fake.calls["create_proposal"] == 1 and len(env.fake.proposals) == 1
    assert env.gw.status()["ok"] is True
    # the original caller retrying afterwards gets the stored result, not a second draft
    again = await env.gw.call("submitter", "create_proposal_draft", args)
    assert again["idempotent_replay"] is True and env.fake.calls["create_proposal"] == 1


async def test_reads_and_dry_runs_are_never_queued(env):
    env.kill()
    with pytest.raises(ToolUnavailable) as e1:
        await env.gw.call("scout", "get_job", {"job_id": "job-1"})
    with pytest.raises(ToolUnavailable) as e2:
        await env.gw.call("submitter", "create_proposal_draft", {
            "job_id": "job-1", "cover_letter": LETTER, "bid_amount": 3, "idempotency_key": "key-dry-00001",
            "dry_run": True})
    assert not e1.value.queued and not e2.value.queued and env.gw.status()["queued"] == 0


async def test_upstream_marketplace_down_also_degrades(env):
    from mcp_servers.marketplace.adapters.base import AdapterError

    async def always(*a, **k):
        raise AdapterError("upstream_unavailable", "GigSim 503")

    env.fake.get_connects = always
    with pytest.raises(ToolUnavailable, match="upstream_unavailable"):
        await env.gw.call("pricing", "get_connects_balance", {})
    assert env.gw.status()["degraded"] == ["marketplace"]


# ------------------------------------------------------------------ approval modes
async def test_strict_mode_requires_explicit_approval_for_real_writes(tmp_path):
    e = Env(tmp_path, approval_mode="strict")
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": "key-strict-001"}
    with pytest.raises(ApprovalRequired):
        await e.gw.call("submitter", "create_proposal_draft", args)
    assert (await e.gw.call("submitter", "create_proposal_draft", {**args, "dry_run": True}))["status"] == "preview"
    ok = await e.gw.call("submitter", "create_proposal_draft", args, approved=True)
    assert ok["status"] == "draft" and ok["proposal_id"]


async def test_bad_transport_config_rejected():
    with pytest.raises(ValueError):
        ToolGateway({"tool_servers": {"transport": "carrier-pigeon"}})


# ------------------------------------------------------------------ the port
async def test_port_is_a_marketplace_port_and_hides_the_adapter(env):
    port = McpMarketplacePort(env.gw, "pricing")
    assert isinstance(port, MarketplacePort)
    assert (await port.get_connects_balance())["balance"] == 100
    assert (await port.get_market_stats("ml"))["p50"] == 350
    assert (await port.as_agent("scout").search_jobs("churn"))[0]["job_id"] == "job-1"
    with pytest.raises(ToolNotAllowed):
        await port.get_client_history("cl-1")  # pricing may not
    assert (await port.as_agent("compliance").get_platform_policy())["connects_per_proposal"] == 8


async def test_port_full_proposal_flow_matches_graph_contract(env):
    sub = McpMarketplacePort(env.gw, "submitter")
    payload = {"job_id": "job-1", "cover_letter": LETTER, "screening_answers": ["PR-AUC"], "bid_amount": 320.0}
    prev = await sub.create_proposal_draft(payload, "key-port-dry-1", dry_run=True)
    assert prev["payload"]["bid_amount"] == 320.0 and prev["connects_cost"] == 8 and prev["balance_after"] == 92
    d = await sub.create_proposal_draft(payload, "key-port-draft1")
    s1 = await sub.submit_proposal(d["proposal_id"], "key-port-sub-1")
    s2 = await sub.submit_proposal(d["proposal_id"], "key-port-sub-1")
    assert s1["status"] == "submitted" and s1["connects_spent"] == 8 and s1["balance"] == 92
    assert s2["idempotent_replay"] and env.fake.balances["alice"] == 92


async def test_graph_expected_shapes_for_liaison_tools(env):
    gw = env.gw
    msgs = await gw.call("client_liaison", "list_messages", {"thread_id": "t1"})
    assert "messages" in msgs
    slots = await gw.call("client_liaison", "get_free_slots", {"days": 5, "duration_minutes": 30})
    assert slots["slots"] and set(slots["slots"][0]) == {"start", "end"}
    hold = await gw.call("client_liaison", "create_interview_hold",
                         {"slot": slots["slots"][0], "client": "Acme", "job_id": ""})
    assert hold["status"] == "tentative"
    ev = await gw.call("client_liaison", "search_evidence", {"requirement": "churn model", "k": 3,
                                                              "portfolio_id": "ai_ml"})
    assert ev["items"][0]["id"]
    sent = await gw.call("client_liaison", "send_message", {"thread_id": "t1", "body": "Hello there",
                                                            "idempotency_key": "conv:alice:t1:m1"})
    assert sent["status"] == "sent"


# ------------------------------------------------------------------ connections
def test_http_connections_carry_bearer_and_user(monkeypatch):
    monkeypatch.setenv("MARKETPLACE_MCP_TOKEN", "tok-abcdefgh")
    c = build_connections({"tool_servers": {"marketplace": {"url": "http://m:1/mcp"}, "timeout_seconds": 7}},
                          "alice", include_optional=["github", "upwork"])
    assert c["marketplace"]["url"] == "http://m:1/mcp" and c["marketplace"]["timeout"] == 7.0
    assert c["marketplace"]["headers"] == {"X-GigBid-User": "alice", "Authorization": "Bearer tok-abcdefgh"}
    assert "Authorization" not in c["portfolio"]["headers"]
    assert c["upwork"]["url"] == "https://mcp.upwork.com/mcp" and "github" in c
    assert "upwork" not in build_connections(None)
