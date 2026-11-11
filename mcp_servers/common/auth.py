"""Bearer-token auth middleware for the streamable-HTTP endpoint (pure ASGI, constant-time)."""
from __future__ import annotations

import hmac
import json

HEALTH_PATH = "/health"


class BearerAuthMiddleware:
    """Rejects any HTTP request without ``Authorization: Bearer <token>`` (401).

    ``/health`` is unauthenticated (liveness only, leaks nothing). The comparison uses
    ``hmac.compare_digest`` so timing does not reveal prefix matches. The token is never logged.
    """

    def __init__(self, app, token: str) -> None:
        if not token or len(token) < 8:
            raise ValueError("bearer token must be set and at least 8 characters")
        self.app = app
        self._token = token.encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if scope["path"] == HEALTH_PATH:
            await self._json(send, 200, {"status": "ok"})
            return
        supplied = b""
        for k, v in scope.get("headers", []):
            if k == b"authorization":
                parts = v.split(b" ", 1)
                if len(parts) == 2 and parts[0].lower() == b"bearer":
                    supplied = parts[1].strip()
                break
        if not hmac.compare_digest(supplied, self._token):
            await self._json(
                send, 401, {"error": "unauthorized", "detail": "invalid bearer token"},
                [(b"www-authenticate", b"Bearer")],
            )
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _json(send, status, body, extra=()):
        payload = json.dumps(body).encode()
        headers = [(b"content-type", b"application/json"),
                   (b"content-length", str(len(payload)).encode()), *extra]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": payload})
