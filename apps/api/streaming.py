"""SSE bridge: turns the services' event iterator (LangGraph stream modes) into an SSE response.

Wire format, one message per graph event::

    event: node_start
    data: {"type":"node_start","node":"job_analyst","ts":"...","data":{...}}

The ``data`` line is always the full RunEvent JSON, so a client may ignore the ``event`` field.
Browsers cannot set an Authorization header on EventSource, so the web client reads this stream with
fetch(); the bearer token never goes into a URL.
"""
from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sse_starlette.sse import EventSourceResponse, ServerSentEvent

from apps.api.errors import ApiError
from apps.api.schemas.runs import RunEvent

log = logging.getLogger(__name__)

PING_SECONDS = 15


def _now() -> str:
    return datetime.now(UTC).isoformat()


def normalise_event(raw: dict[str, Any] | RunEvent) -> dict[str, Any]:
    """Validate against RunEvent so a buggy producer cannot break the client contract."""
    event = raw if isinstance(raw, RunEvent) else RunEvent.model_validate(raw)
    return event.model_dump(mode="json")


async def _encode(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[ServerSentEvent]:
    try:
        async for raw in events:
            payload = normalise_event(raw)
            yield ServerSentEvent(data=json.dumps(payload), event=payload["type"])
    except ApiError as exc:
        payload = {"type": "error", "node": None, "ts": _now(), "data": {"detail": exc.detail}}
        yield ServerSentEvent(data=json.dumps(payload), event="error")
    except Exception:  # noqa: BLE001 - surface any producer failure as a typed error event
        log.exception("run stream failed")
        payload = {"type": "error", "node": None, "ts": _now(), "data": {"detail": "stream failed"}}
        yield ServerSentEvent(data=json.dumps(payload), event="error")


def sse_response(events: AsyncIterator[dict[str, Any]]) -> EventSourceResponse:
    return EventSourceResponse(
        _encode(events),
        ping=PING_SECONDS,
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
