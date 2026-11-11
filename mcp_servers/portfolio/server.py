"""GigBid Portfolio MCP server (read-only).

Run:  python -m mcp_servers.portfolio [--transport stdio|streamable-http] [--port 9101]
Test: ``build_server(config, retriever=fake)`` + an in-memory MCP client session.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os

from mcp.server.fastmcp import FastMCP

from .prompts import register_prompts
from .resources import register_resources
from .service import PortfolioConfig, PortfolioService, RetrieverSource
from .tools import register_tools

INSTRUCTIONS = (
    "Read-only access to a freelancer's portfolio: case studies, READMEs, code, reviews and past "
    "proposals with outcomes. Call search_evidence once per atomic requirement and cite the "
    "returned evidence ids. Nothing here can change data or contact anyone."
)


def build_server(
    config: PortfolioConfig | dict | None = None, retriever: RetrieverSource = None
) -> FastMCP:
    """Build the FastMCP server. ``retriever`` may be an object with ``.search`` or a factory
    ``portfolio_id -> retriever`` (tests inject a fake; production selects rag or local)."""
    if isinstance(config, dict):
        config = PortfolioConfig(**config)
    svc = PortfolioService(config, retriever)
    mcp = FastMCP("gigbid-portfolio", instructions=INSTRUCTIONS)
    register_tools(mcp, svc)
    register_resources(mcp, svc)
    register_prompts(mcp, svc)
    mcp._gigbid_service = svc  # type: ignore[attr-defined]  # handy for tests
    return mcp


class _Bearer:
    """Minimal constant-time bearer check (kept local: this package is published standalone)."""

    def __init__(self, app, token: str) -> None:
        self.app, self.token = app, token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope["headers"]).get(b"authorization", b"")
            ok = auth[:7].lower() == b"bearer " and hmac.compare_digest(auth[7:].strip(), self.token)
            if scope["path"] == "/health":
                body, status = b'{"status":"ok"}', 200
            elif not ok:
                body, status = json.dumps({"error": "unauthorized"}).encode(), 401
            else:
                return await self.app(scope, receive, send)
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json")]})
            return await send({"type": "http.response.body", "body": body})
        return await self.app(scope, receive, send)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="gigbid-portfolio-mcp")
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9101)
    ap.add_argument("--insecure-no-auth", action="store_true")
    args = ap.parse_args(argv)
    server = build_server()
    if args.transport == "stdio":
        server.run("stdio")
        return
    token = os.getenv("PORTFOLIO_MCP_TOKEN", "")
    if len(token) < 8 and not args.insecure_no_auth:
        raise SystemExit("PORTFOLIO_MCP_TOKEN (>= 8 chars) must be set for HTTP, or pass --insecure-no-auth")
    import uvicorn

    app = server.streamable_http_app()
    if token:
        app = _Bearer(app, token)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
