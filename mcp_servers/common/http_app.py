"""Authenticated streamable-HTTP ASGI app + a tiny CLI runner for a FastMCP server."""
from __future__ import annotations

import argparse
import os
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from .auth import BearerAuthMiddleware


def build_http_app(server: FastMCP, token: str | None):
    """Streamable-HTTP app. ``token=None`` means no auth (local dev only, explicit opt-in)."""
    app = server.streamable_http_app()
    if token is not None:
        if len(token) < 8:  # fail at build time, not lazily at first request
            raise ValueError("bearer token must be set and at least 8 characters")
        app.add_middleware(BearerAuthMiddleware, token=token)
    return app


def run_cli(
    name: str,
    build: Callable[[], FastMCP],
    *,
    token_env: str,
    default_port: int,
    argv: list[str] | None = None,
) -> None:
    ap = argparse.ArgumentParser(prog=name)
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=default_port)
    ap.add_argument("--insecure-no-auth", action="store_true",
                    help="serve HTTP without bearer auth (local development only)")
    args = ap.parse_args(argv)
    server = build()
    if args.transport == "stdio":
        server.run("stdio")
        return
    token = os.getenv(token_env)
    if not token and not args.insecure_no_auth:
        raise SystemExit(f"{token_env} must be set for HTTP transport (or pass --insecure-no-auth)")
    import uvicorn

    server.settings.host, server.settings.port = args.host, args.port
    uvicorn.run(build_http_app(server, token or None), host=args.host, port=args.port,
                log_level="info")
