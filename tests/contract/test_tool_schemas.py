"""Schema snapshot: any change to a tool's name, description, input/output schema or annotations
(or to a resource template / prompt) fails CI until the snapshot is regenerated on purpose:

    UPDATE_SNAPSHOTS=1 pytest tests/contract/test_tool_schemas.py

Review the resulting diff of tests/contract/snapshots/tool_schemas.json like an API change.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.marketplace import build_server as build_marketplace
from mcp_servers.marketplace.service import MarketplaceConfig
from mcp_servers.marketplace.tests.fakes import FakeMarketplace
from mcp_servers.portfolio import build_server as build_portfolio
from mcp_servers.portfolio.service import PortfolioConfig
from mcp_servers.workspace import WorkspaceConfig
from mcp_servers.workspace import build_server as build_workspace

SNAPSHOT = Path(__file__).parent / "snapshots" / "tool_schemas.json"


async def dump_server(server) -> dict:
    async with connect(server) as c:
        tools = (await c.list_tools()).tools
        templates = (await c.list_resource_templates()).resourceTemplates
        prompts = (await c.list_prompts()).prompts
    return {
        "tools": {
            t.name: {
                "description": t.description,
                "inputSchema": t.inputSchema,
                "outputSchema": t.outputSchema,
                "annotations": t.annotations.model_dump(exclude_none=True) if t.annotations else None,
            }
            for t in sorted(tools, key=lambda t: t.name)
        },
        "resource_templates": sorted(r.uriTemplate for r in templates),
        "prompts": {
            p.name: sorted((a.name, bool(a.required)) for a in (p.arguments or []))
            for p in sorted(prompts, key=lambda p: p.name)
        },
    }


async def current_snapshot(tmp_path: Path) -> dict:
    servers = {
        "marketplace": build_marketplace(MarketplaceConfig(adapter=FakeMarketplace(), state_dir=tmp_path / "m")),
        "portfolio": build_portfolio(PortfolioConfig(data_dir=str(tmp_path), backend="local")),
        "workspace": build_workspace(WorkspaceConfig(store_path=tmp_path / "w.json")),
    }
    return {name: await dump_server(srv) for name, srv in servers.items()}


def render(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


async def test_tool_schemas_match_snapshot(tmp_path):
    actual = render(await current_snapshot(tmp_path))
    if os.getenv("UPDATE_SNAPSHOTS") == "1":
        SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT.write_text(actual, encoding="utf-8", newline="\n")
        return
    if not SNAPSHOT.exists():
        pytest.fail(f"no snapshot at {SNAPSHOT}; run with UPDATE_SNAPSHOTS=1 to create it")
    expected = SNAPSHOT.read_text(encoding="utf-8")
    if expected != actual:
        old, new = json.loads(expected), json.loads(actual)
        changed = sorted(
            f"{srv}.{tool}"
            for srv in set(old) | set(new)
            for tool in set(old.get(srv, {}).get("tools", {})) | set(new.get(srv, {}).get("tools", {}))
            if old.get(srv, {}).get("tools", {}).get(tool) != new.get(srv, {}).get("tools", {}).get(tool)
        )
        pytest.fail(
            "MCP tool schema changed unintentionally. Changed tools: "
            f"{changed or 'resources/prompts only'}. If intended, regenerate with "
            "UPDATE_SNAPSHOTS=1 and review the diff."
        )


async def test_every_tool_has_description_and_output_schema_and_annotations(tmp_path):
    snap = await current_snapshot(tmp_path)
    for server, body in snap.items():
        for name, t in body["tools"].items():
            assert t["description"] and len(t["description"]) > 40, (server, name)
            assert t["outputSchema"], (server, name)
            a = t["annotations"] or {}
            assert {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"} <= set(a), (server, name)
            if a["readOnlyHint"] is False and server == "marketplace":
                assert "idempotency_key" in t["inputSchema"]["required"], name
