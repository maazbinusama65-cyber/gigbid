"""GigBid Workspace MCP server: calendar availability, tentative interview holds, email drafts.

BACKING STORE: a local mock (JSON file) with a deterministic working-hours calendar, NOT Google
Calendar / Gmail. Agents only ever see these MCP tools, so a Google-backed implementation can
replace ``WorkspaceStore`` without touching the graph. There is intentionally no "send email"
tool: drafts are never sent.

Run:  python -m mcp_servers.workspace --transport streamable-http --port 9103
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from ..common.audit import AuditLog
from ..common.context import resolve_context
from ..common.http_app import run_cli

WORK_START, WORK_END = time(9, 0), time(17, 0)
GRID_MINUTES = 30
LUNCH = (time(12, 0), time(13, 0))
READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False)


# ----------------------------------------------------------------------------- models
class Slot(BaseModel):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?$",
                       description="ISO start time (UTC), e.g. 2026-03-02T14:00")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?Z?$",
                            description="ISO end time; omit to use duration_minutes.")


class FreeSlots(BaseModel):
    slots: list[Slot]
    timezone: str = "UTC"
    working_hours: str = "Mon-Fri 09:00-17:00, lunch 12:00-13:00 blocked"


class InterviewHold(BaseModel):
    hold_id: str
    status: str = Field(description="always 'tentative': the client has not been told")
    slot: Slot
    client: str
    job_id: str | None = None
    already_existed: bool = Field(default=False, description="True when this exact hold existed.")


class EmailDraft(BaseModel):
    draft_id: str
    status: str = Field(description="always 'draft': nothing is ever sent")
    to: str
    subject: str
    already_existed: bool = False


# ----------------------------------------------------------------------------- calendar logic
def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.rstrip("Z")).replace(second=0, microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def deterministic_busy(day: date) -> list[tuple[datetime, datetime]]:
    """Fixed per-date pseudo-meeting so availability is reproducible: lunch every day plus, on
    about 60% of days, one 1-hour meeting at a hash-derived hour between 10:00 and 15:00."""
    busy = [(datetime.combine(day, LUNCH[0]), datetime.combine(day, LUNCH[1]))]
    h = int(hashlib.sha256(day.isoformat().encode()).hexdigest(), 16)
    if h % 10 < 6:
        hour = 10 + (h // 10) % 5
        if hour != 12:
            busy.append((datetime.combine(day, time(hour, 0)), datetime.combine(day, time(hour + 1, 0))))
    return busy


def _overlaps(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


class WorkspaceStore:
    """JSON-file store (atomic writes), partitioned by user id."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"users": {}}
        return json.loads(self.path.read_text(encoding="utf-8") or '{"users": {}}')

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ws")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
        os.replace(tmp, self.path)

    def holds(self, user: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._load()["users"].get(user, {}).get("holds", []))

    def add(self, user: str, kind: str, record: dict[str, Any], id_key: str) -> tuple[dict[str, Any], bool]:
        with self._lock:
            data = self._load()
            bucket = data["users"].setdefault(user, {"holds": [], "drafts": []})[kind]
            for r in bucket:
                if r[id_key] == record[id_key]:
                    return r, True
            bucket.append(record)
            self._save(data)
            return record, False

    def drafts(self, user: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._load()["users"].get(user, {}).get("drafts", []))


def free_slots(store: WorkspaceStore, user: str, start: date, days: int, duration: int,
               limit: int) -> list[Slot]:
    held = [(_parse(h["slot"]["start"]), _parse(h["slot"]["end"])) for h in store.holds(user)]
    out: list[Slot] = []
    for d in range(days):
        day = start + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        busy = deterministic_busy(day) + held
        cur = datetime.combine(day, WORK_START)
        end_of_day = datetime.combine(day, WORK_END)
        while cur + timedelta(minutes=duration) <= end_of_day:
            nxt = cur + timedelta(minutes=duration)
            if not any(_overlaps(cur, nxt, b0, b1) for b0, b1 in busy):
                out.append(Slot(start=_iso(cur), end=_iso(nxt)))
                if len(out) >= limit:
                    return out
            cur += timedelta(minutes=GRID_MINUTES)
    return out


@dataclass
class WorkspaceConfig:
    store_path: str | Path = field(default_factory=lambda: os.getenv(
        "WORKSPACE_STORE", "data/processed/workspace_mock/store.json"))
    audit_path: str | Path | None = None
    default_user: str = field(default_factory=lambda: os.getenv("WORKSPACE_DEFAULT_USER", "default"))
    today: Callable[[], date] = date.today  # injectable for deterministic tests


def _hid(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]


def build_server(config: WorkspaceConfig | None = None) -> FastMCP:
    cfg = config or WorkspaceConfig()
    store = WorkspaceStore(cfg.store_path)
    audit = AuditLog(cfg.audit_path or Path(cfg.store_path).with_name("audit.jsonl"))
    mcp = FastMCP("gigbid-workspace", instructions=(
        "Calendar availability, TENTATIVE interview holds and email DRAFTS (mock local store). "
        "Nothing is sent to anyone; a human confirms holds and sends drafts."))

    @mcp.tool(title="Get free calendar slots", annotations=READ)
    def get_free_slots(
        ctx: Context,
        days: Annotated[int, Field(ge=1, le=14, description="How many calendar days ahead to scan.")] = 5,
        duration_minutes: Annotated[int, Field(ge=15, le=240, description="Meeting length.")] = 30,
        from_date: Annotated[str | None, Field(pattern=r"^\d{4}-\d{2}-\d{2}$",
                                               description="First day to scan; default tomorrow.")] = None,
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum slots returned.")] = 20,
    ) -> FreeSlots:
        """Free interview slots in the freelancer's working hours (Mon-Fri 09:00-17:00 UTC,
        lunch blocked, existing meetings and tentative holds excluded), earliest first."""
        c = resolve_context(ctx, cfg.default_user)
        start = date.fromisoformat(from_date) if from_date else cfg.today() + timedelta(days=1)
        return FreeSlots(slots=free_slots(store, c.user, start, days, duration_minutes, limit))

    @mcp.tool(title="Create tentative interview hold", annotations=WRITE)
    def create_interview_hold(
        ctx: Context,
        slot: Slot,
        client: Annotated[str, Field(min_length=1, max_length=100, description="Client name.")],
        job_id: Annotated[str | None, Field(max_length=64, description="Related job id.")] = None,
        duration_minutes: Annotated[int, Field(ge=15, le=240,
                                               description="Used only when slot.end is omitted.")] = 30,
    ) -> InterviewHold:
        """Block a slot on the calendar as TENTATIVE for an interview with a client. Fails if the
        slot is outside working hours or already busy. Repeating the identical request returns the
        existing hold, never a duplicate. The client is not notified."""
        c = resolve_context(ctx, cfg.default_user)
        start = _parse(slot.start)
        end = _parse(slot.end) if slot.end else start + timedelta(minutes=duration_minutes)
        if end <= start or end - start > timedelta(hours=4):
            raise ToolError("invalid_slot: end must be after start and at most 4 hours later")
        day_open, day_close = (datetime.combine(start.date(), WORK_START), datetime.combine(start.date(), WORK_END))
        if start.weekday() >= 5 or start < day_open or end > day_close or end.date() != start.date():
            raise ToolError("slot_unavailable: outside working hours (Mon-Fri 09:00-17:00 UTC)")
        hold_id = _hid("hold_", c.user, _iso(start), _iso(end), client, job_id or "")
        existing = {h["hold_id"] for h in store.holds(c.user)}
        if hold_id not in existing:
            busy = deterministic_busy(start.date()) + [
                (_parse(h["slot"]["start"]), _parse(h["slot"]["end"])) for h in store.holds(c.user)]
            if any(_overlaps(start, end, b0, b1) for b0, b1 in busy):
                raise ToolError("slot_unavailable: the slot conflicts with an existing event or hold")
        rec = {"hold_id": hold_id, "status": "tentative", "slot": {"start": _iso(start), "end": _iso(end)},
               "client": client, "job_id": job_id}
        stored, dup = store.add(c.user, "holds", rec, "hold_id")
        audit.record(user=c.user, tool="create_interview_hold", arguments=rec, trace_id=c.trace_id, ok=True,
                     result_summary=f"hold_id={hold_id} already_existed={dup}")
        return InterviewHold(**stored, already_existed=dup)

    @mcp.tool(title="Create email draft", annotations=WRITE)
    def create_email_draft(
        ctx: Context,
        to: Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254,
                                 description="Recipient address.")],
        subject: Annotated[str, Field(min_length=1, max_length=200)],
        body: Annotated[str, Field(min_length=1, max_length=10000)],
    ) -> EmailDraft:
        """Save an email as a DRAFT for the human to review and send. This server cannot send
        email. Saving the identical draft twice returns the same draft id."""
        c = resolve_context(ctx, cfg.default_user)
        draft_id = _hid("draft_", c.user, to.lower(), subject, body)
        rec = {"draft_id": draft_id, "status": "draft", "to": to, "subject": subject, "body": body}
        stored, dup = store.add(c.user, "drafts", rec, "draft_id")
        audit.record(user=c.user, tool="create_email_draft", arguments={"to": to, "subject": subject, "body": body},
                     trace_id=c.trace_id, ok=True, result_summary=f"draft_id={draft_id} already_existed={dup}")
        return EmailDraft(draft_id=draft_id, status="draft", to=to, subject=subject, already_existed=dup)

    mcp._gigbid_store = store  # type: ignore[attr-defined]
    return mcp


def main(argv: list[str] | None = None) -> None:
    run_cli("gigbid-workspace-mcp", build_server, token_env="WORKSPACE_MCP_TOKEN", default_port=9103, argv=argv)


if __name__ == "__main__":
    main()
