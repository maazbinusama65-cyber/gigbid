"""Per-call context: acting user and trace id, from MCP ``_meta`` / HTTP header / tool argument."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

USER_HEADER = "x-gigbid-user"


@dataclass(frozen=True)
class CallContext:
    user: str
    trace_id: str | None


def resolve_context(ctx: Any, default_user: str, arg_trace_id: str | None = None) -> CallContext:
    """Tenant id is never a model-controlled tool argument: it comes from the transport.

    Order: MCP ``_meta.user_id`` (set by ToolGateway) > ``X-GigBid-User`` header > default user.
    """
    user, trace = None, arg_trace_id
    try:
        rc = ctx.request_context
    except Exception:  # noqa: BLE001 - no active request (e.g. function called directly)
        rc = None
    if rc is not None:
        meta = getattr(rc, "meta", None)
        extra = (getattr(meta, "model_extra", None) or {}) if meta is not None else {}
        user = extra.get("user_id")
        trace = trace or extra.get("trace_id")
        req = getattr(rc, "request", None)
        headers = getattr(req, "headers", None)
        if headers is not None:
            user = user or headers.get(USER_HEADER)
            trace = trace or headers.get("x-trace-id")
    return CallContext(user=str(user or default_user), trace_id=trace)
