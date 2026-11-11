from __future__ import annotations

from datetime import date

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.workspace import WorkspaceConfig, build_server
from mcp_servers.workspace.server import deterministic_busy

TODAY = date(2026, 3, 2)  # a Monday


@pytest.fixture()
def cfg(tmp_path):
    return WorkspaceConfig(store_path=tmp_path / "ws" / "store.json", default_user="alice",
                           today=lambda: TODAY)


async def slots(c, **args):
    r = await c.call_tool("get_free_slots", args)
    assert not r.isError, r.content
    return r.structuredContent["slots"]


async def test_inventory_and_annotations(cfg):
    async with connect(build_server(cfg)) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == {"get_free_slots", "create_interview_hold", "create_email_draft"}
    assert tools["get_free_slots"].annotations.readOnlyHint is True
    for n in ("create_interview_hold", "create_email_draft"):
        a = tools[n].annotations
        assert a.readOnlyHint is False and a.destructiveHint is False and a.idempotentHint is True
    assert all(t.outputSchema for t in tools.values())


async def test_free_slots_deterministic_working_hours_only(cfg):
    async with connect(build_server(cfg)) as c:
        a = await slots(c, days=7, duration_minutes=60, limit=50, from_date="2026-03-02")
        b = await slots(c, days=7, duration_minutes=60, limit=50, from_date="2026-03-02")
    assert a == b and a
    for s in a:
        st, en = s["start"], s["end"]
        d = date.fromisoformat(st[:10])
        assert d.weekday() < 5
        assert "09:00" <= st[11:] and en[11:] <= "17:00"
        assert not ("12:00" <= st[11:] < "13:00")  # lunch blocked
    busy = {(b0.isoformat(timespec="minutes"), b1.isoformat(timespec="minutes"))
            for d in range(7) for b0, b1 in deterministic_busy(date(2026, 3, 2 + d))}
    for s in a:  # never overlaps deterministic meetings
        assert all(not (s["start"] < b1 and b0 < s["end"]) for b0, b1 in busy)


async def test_default_start_is_tomorrow_and_weekends_skipped(cfg):
    async with connect(build_server(cfg)) as c:
        s = await slots(c, days=14, limit=50)
    assert s[0]["start"].startswith("2026-03-03")
    assert not any(date.fromisoformat(x["start"][:10]).weekday() >= 5 for x in s)


async def test_input_constraints(cfg):
    async with connect(build_server(cfg)) as c:
        for args in ({"days": 0}, {"days": 15}, {"duration_minutes": 5}, {"from_date": "tomorrow"}):
            assert (await c.call_tool("get_free_slots", args)).isError


async def test_hold_is_idempotent_and_removes_slot_from_availability(cfg):
    async with connect(build_server(cfg)) as c:
        first_free = (await slots(c, days=3, from_date="2026-03-02"))[0]
        args = {"slot": first_free, "client": "Acme", "job_id": "j1"}
        h1 = await c.call_tool("create_interview_hold", args)
        h2 = await c.call_tool("create_interview_hold", args)
        after = await slots(c, days=3, from_date="2026-03-02")
    assert h1.structuredContent["status"] == "tentative" and h1.structuredContent["already_existed"] is False
    assert h2.structuredContent["hold_id"] == h1.structuredContent["hold_id"]
    assert h2.structuredContent["already_existed"] is True
    assert first_free not in after
    assert len(build_server(cfg)._gigbid_store.holds("alice")) == 1


async def test_hold_conflicts_and_outside_hours_rejected(cfg):
    async with connect(build_server(cfg)) as c:
        lunch = await c.call_tool("create_interview_hold", {"slot": {"start": "2026-03-02T12:00"}, "client": "A"})
        night = await c.call_tool("create_interview_hold", {"slot": {"start": "2026-03-02T20:00"}, "client": "A"})
        sat = await c.call_tool("create_interview_hold", {"slot": {"start": "2026-03-07T10:00"}, "client": "A"})
        bad = await c.call_tool("create_interview_hold", {"slot": {"start": "2026-03-02T10:00", "end": "2026-03-02T09:00"},
                                                          "client": "A"})
        free = (await slots(c, days=2, from_date="2026-03-02"))[0]
        await c.call_tool("create_interview_hold", {"slot": free, "client": "A"})
        clash = await c.call_tool("create_interview_hold", {"slot": free, "client": "B"})
    for r in (lunch, night, sat, bad, clash):
        assert r.isError
    assert "slot_unavailable" in lunch.content[0].text and "slot_unavailable" in clash.content[0].text


async def test_email_draft_saved_never_sent_and_idempotent(cfg):
    args = {"to": "client@example.com", "subject": "Interview times", "body": "Tuesday 10:00 works."}
    async with connect(build_server(cfg)) as c:
        d1 = await c.call_tool("create_email_draft", args)
        d2 = await c.call_tool("create_email_draft", args)
        bad = await c.call_tool("create_email_draft", {**args, "to": "not-an-email"})
        names = {t.name for t in (await c.list_tools()).tools}
    assert d1.structuredContent["status"] == "draft"
    assert d2.structuredContent["draft_id"] == d1.structuredContent["draft_id"] and d2.structuredContent["already_existed"]
    assert bad.isError
    assert not any("send" in n for n in names)  # there is no way to send


async def test_tenants_are_isolated(cfg):
    async with connect(build_server(cfg)) as c:
        free = (await slots(c, days=2, from_date="2026-03-02"))[0]
        await c.call_tool("create_interview_hold", {"slot": free, "client": "A"}, meta={"user_id": "alice"})
        r = await c.call_tool("get_free_slots", {"days": 2, "from_date": "2026-03-02"}, meta={"user_id": "bob"})
        ok = await c.call_tool("create_interview_hold", {"slot": free, "client": "A"}, meta={"user_id": "bob"})
    assert free in r.structuredContent["slots"] and not ok.isError
