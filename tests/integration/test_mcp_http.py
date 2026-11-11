"""Real Streamable-HTTP path: uvicorn thread + bearer auth + MultiServerMCPClient via ToolGateway.

Includes the viva scenario: kill the marketplace server -> ToolUnavailable + status message +
queued write -> restart -> recover() replays it exactly once.
"""
from __future__ import annotations

import socket
import threading
import time

import pytest
import uvicorn

from agent.tools import ToolGateway, ToolUnavailable
from mcp_servers.common.http_app import build_http_app
from mcp_servers.marketplace import build_server
from mcp_servers.marketplace.service import MarketplaceConfig
from mcp_servers.marketplace.tests.fakes import FakeMarketplace

TOKEN = "integration-token-123"
LETTER = "I built a churn model with scikit-learn and would love to help you ship yours."


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Live:
    def __init__(self, server, port: int, token: str = TOKEN) -> None:
        self.port = port
        self.uv = uvicorn.Server(uvicorn.Config(build_http_app(server, token), host="127.0.0.1", port=port,
                                                log_level="warning",
                                                timeout_graceful_shutdown=1))
        self.thread = threading.Thread(target=self.uv.run, daemon=True)

    def start(self) -> Live:
        self.thread.start()
        for _ in range(100):
            if self.uv.started:
                return self
            time.sleep(0.05)
        raise RuntimeError("server did not start")

    def stop(self) -> None:
        self.uv.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture()
def stack(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKETPLACE_MCP_TOKEN", TOKEN)
    fake = FakeMarketplace()
    port = free_port()

    def make() -> Live:
        cfg = MarketplaceConfig(adapter=fake, state_dir=tmp_path / "st", default_user="alice",
                                rate_limit_rpm=600, rate_burst=100)
        return Live(build_server(cfg), port).start()

    live = make()
    cfg = {"tool_servers": {"transport": "http", "marketplace": {"url": f"http://127.0.0.1:{port}/mcp"},
                            "timeout_seconds": 5, "retries": 1, "backoff_seconds": 0.01, "cooldown_seconds": 0}}
    gw = ToolGateway(cfg, user_id="alice")
    yield fake, gw, live, make
    live.stop()


async def test_http_calls_with_bearer_and_user_header(stack):
    fake, gw, _, _ = stack
    res = await gw.call("pricing", "get_connects_balance", {})
    assert res["balance"] == 100 and fake.users_seen == ["alice"]
    assert (await gw.call("scout", "search_jobs", {"query": "churn"}))["jobs"][0]["job_id"] == "job-1"


async def test_http_wrong_token_is_unavailable_not_a_crash(stack, monkeypatch):
    _, gw, _, _ = stack
    monkeypatch.setenv("MARKETPLACE_MCP_TOKEN", "wrong-token-123")
    url = gw._shared.connections["marketplace"]["url"]
    bad = ToolGateway({"tool_servers": {"transport": "http", "marketplace": {"url": url}, "retries": 0,
                                        "timeout_seconds": 5}}, user_id="alice")
    with pytest.raises(ToolUnavailable):
        await bad.call("pricing", "get_connects_balance", {})


async def test_kill_server_degrade_queue_restart_recover(stack):
    fake, gw, live, make = stack
    assert (await gw.call("pricing", "get_connects_balance", {}))["balance"] == 100
    live.stop()  # "kill the marketplace server during the viva"
    with pytest.raises(ToolUnavailable):
        await gw.call("scout", "get_job", {"job_id": "job-1"})
    st = gw.status()
    assert st["ok"] is False and "marketplace" in st["message"]
    args = {"job_id": "job-1", "cover_letter": LETTER, "bid_amount": 300, "idempotency_key": "key-http-0001"}
    with pytest.raises(ToolUnavailable) as e:
        await gw.call("submitter", "create_proposal_draft", args)
    assert e.value.queued and gw.status()["queued"] == 1
    make()  # restart
    out = await gw.recover()
    assert out["recovered"] == ["marketplace"] and len(out["replayed"]) == 1
    assert fake.calls["create_proposal"] == 1 and gw.status()["ok"]
