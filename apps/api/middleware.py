"""Pure-ASGI trace-id middleware (safe for SSE, unlike BaseHTTPMiddleware)."""
from __future__ import annotations

import json
import logging
import re
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.api.logging_setup import trace_id_var

log = logging.getLogger("apps.api")
TRACE_HEADER = "x-trace-id"
_VALID = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")


class TraceIdMiddleware:
    """Accept or mint a trace id, expose it to the request (contextvar) and echo it back."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(TRACE_HEADER.encode(), b"").decode()
        trace_id = incoming if _VALID.match(incoming) else uuid.uuid4().hex
        token = trace_id_var.set(trace_id)
        scope.setdefault("state", {})["trace_id"] = trace_id
        started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = [h for h in message.get("headers", []) if h[0].lower() != TRACE_HEADER.encode()]
                headers.append((b"x-trace-id", trace_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:  # noqa: BLE001 - last-resort JSON 500 that still carries the trace id
            log.exception("unhandled error")
            if scope["type"] == "http" and not started:
                body = json.dumps(
                    {"error": "internal_error", "detail": "Unexpected server error", "trace_id": trace_id}
                ).encode()
                await send_wrapper(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                    }
                )
                await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            trace_id_var.reset(token)
