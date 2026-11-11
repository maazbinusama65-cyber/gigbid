"""MCP client setup: server connections + per-agent tool allowlists (A5, A6).

Agents never see a tool they do not need: the allowlist is filtered by tool NAME, per agent, and is
enforced by ``agent.tools.ToolGateway`` (and by ``tools_for_agent`` for LangChain tool lists).
"""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any

# --------------------------------------------------------------------------- tool inventory
MARKETPLACE_READ = frozenset({
    "search_jobs", "get_job", "get_client_history", "get_connects_balance", "list_messages",
    "list_events", "get_market_stats", "get_platform_policy",
})
MARKETPLACE_WRITE = frozenset({"create_proposal_draft", "submit_proposal", "send_message"})
PORTFOLIO_READ = frozenset({"search_evidence", "get_case_study", "list_skills"})
WORKSPACE_TOOLS = frozenset({"get_free_slots", "create_interview_hold", "create_email_draft"})
GITHUB_READ = frozenset({"get_file_contents", "search_repositories", "search_code", "list_commits"})

SERVERS = ("marketplace", "portfolio", "workspace")
OPTIONAL_SERVERS = ("github", "upwork")

# Tools with external side effects. Real (non dry-run) calls need human approval upstream; in
# ToolGateway(approval_mode="strict") the caller must additionally pass approved=True.
WRITE_TOOLS = MARKETPLACE_WRITE | {"create_interview_hold", "create_email_draft"}
APPROVAL_REQUIRED_TOOLS = WRITE_TOOLS

_NONE: dict[str, frozenset[str]] = {}


def _al(**kw: Iterable[str]) -> dict[str, frozenset[str]]:
    return {server: frozenset(tools) for server, tools in kw.items()}


AGENT_ALLOWLISTS: dict[str, dict[str, frozenset[str]]] = {
    "scout": _al(marketplace={"search_jobs", "get_job"}),
    "analyst": _NONE,                      # Job Analyst: works on text already in state
    "job_analyst": _NONE,
    "risk_assessor": _al(marketplace={"get_client_history", "get_job"}),
    "fit_matcher": _al(portfolio=PORTFOLIO_READ),
    "pricing": _al(marketplace={"get_market_stats", "get_connects_balance", "get_job"}),
    "writer": _al(portfolio=PORTFOLIO_READ),
    "critic": _al(portfolio=PORTFOLIO_READ),
    "verifier": _al(portfolio=PORTFOLIO_READ),
    "compliance": _al(marketplace={"get_platform_policy"}),
    # approval-gated executor node: the ONLY agent allowed to create/submit proposals
    "submitter": _al(marketplace={"create_proposal_draft", "submit_proposal"}),
    "client_liaison": _al(
        marketplace=MARKETPLACE_READ | {"send_message"},
        workspace=WORKSPACE_TOOLS,
        portfolio={"search_evidence"},
    ),
    # RAG ingestion of repos through the third-party GitHub MCP server (optional)
    "ingest": _al(github=GITHUB_READ),
}


def allowed_tools(agent: str) -> dict[str, frozenset[str]]:
    """server -> allowed tool names for the agent (empty dict for unknown or tool-less agents)."""
    return AGENT_ALLOWLISTS.get(agent, _NONE)


def server_for(agent: str, tool: str) -> str | None:
    for server, tools in allowed_tools(agent).items():
        if tool in tools:
            return server
    return None


def is_allowed(agent: str, tool: str) -> bool:
    return server_for(agent, tool) is not None


# --------------------------------------------------------------------------- connections
DEFAULT_URLS = {
    "marketplace": "http://localhost:9102/mcp",
    "portfolio": "http://localhost:9101/mcp",
    "workspace": "http://localhost:9103/mcp",
}

# Third-party servers (docs/TOOLS.md has the trust rationale). Optional: off unless requested.
UPWORK_SERVER = {"transport": "streamable_http", "url": "https://mcp.upwork.com/mcp"}  # per-user OAuth bearer
GITHUB_SERVER_REMOTE = {"transport": "streamable_http", "url": "https://api.githubcopilot.com/mcp/"}
GITHUB_SERVER_DOCKER = {
    "transport": "stdio", "command": "docker",
    "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
             "-e", "GITHUB_READ_ONLY=1", "ghcr.io/github/github-mcp-server"],
}


def build_connections(
    cfg: Mapping[str, Any] | None,
    user_id: str = "default",
    *,
    include_optional: Iterable[str] = (),
) -> dict[str, dict[str, Any]]:
    """Connection dicts for ``MultiServerMCPClient`` (Streamable HTTP, bearer + user header)."""
    ts = dict((cfg or {}).get("tool_servers", {}) or {})
    timeout = float(ts.get("timeout_seconds", 20))
    conns: dict[str, dict[str, Any]] = {}
    for name in SERVERS:
        url = os.getenv(f"{name.upper()}_MCP_URL") or (ts.get(name) or {}).get("url") or DEFAULT_URLS[name]
        headers = {"X-GigBid-User": user_id}
        token = os.getenv(f"{name.upper()}_MCP_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        conns[name] = {"transport": "streamable_http", "url": url, "headers": headers, "timeout": timeout}
    wanted = set(include_optional)
    if "upwork" in wanted:
        conns["upwork"] = dict(UPWORK_SERVER)
    if "github" in wanted:
        pat = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
        if os.getenv("GITHUB_MCP_MODE", "remote") == "docker":
            conns["github"] = {**GITHUB_SERVER_DOCKER, "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": pat or ""}}
        else:
            conns["github"] = {**GITHUB_SERVER_REMOTE,
                               "headers": {"Authorization": f"Bearer {pat}"} if pat else {}}
    return conns


def make_client(cfg: Mapping[str, Any] | None, user_id: str = "default", *,
                include_optional: Iterable[str] = ()):
    from langchain_mcp_adapters.client import MultiServerMCPClient

    return MultiServerMCPClient(build_connections(cfg, user_id, include_optional=include_optional))


async def tools_for_agent(client: Any, agent: str) -> list[Any]:
    """LangChain tools for one agent, filtered by name against its allowlist."""
    out: list[Any] = []
    for server, names in allowed_tools(agent).items():
        out.extend(t for t in await client.get_tools(server_name=server) if t.name in names)
    return out
