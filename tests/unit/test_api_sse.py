# ruff: noqa: F811
"""SSE run stream, approvals flow and degraded mode (mock services)."""
from __future__ import annotations

from .api_fixtures import app, client, read_sse, reviewer  # noqa: F401

ALLOWED = {"node_start", "node_end", "interrupt", "token", "done", "error", "degraded"}


def test_stream_emits_ordered_typed_events_and_ends_awaiting_approval(client, reviewer):
    run_id = client.post("/api/jobs/job_1007/analyze", headers=reviewer).json()["run_id"]
    events = read_sse(client, run_id, reviewer)
    types = [e["type"] for e in events]
    assert set(types) <= ALLOWED
    assert {"node_start", "node_end", "token", "interrupt", "done"} <= set(types)
    assert all({"type", "node", "ts", "data"} <= set(e) for e in events)
    nodes_ended = [e["node"] for e in events if e["type"] == "node_end"]
    assert nodes_ended[-1] == "compliance" and "writer" in nodes_ended
    assert types.index("interrupt") < types.index("done") == len(types) - 1
    assert events[-1]["data"]["status"] == "awaiting_approval"
    approval_id = next(e for e in events if e["type"] == "interrupt")["data"]["approval_id"]
    pending = {a["approval_id"] for a in client.get("/api/approvals?status=pending", headers=reviewer).json()["approvals"]}
    assert approval_id in pending
    # replay returns the same events without re-running the graph
    assert [e["type"] for e in read_sse(client, run_id, reviewer)] == types


def test_scam_job_run_skips_without_an_approval(client, reviewer):
    detail = client.get("/api/runs/run_1003", headers=reviewer).json()
    assert detail["summary"]["status"] == "skipped" and detail["approval_id"] is None
    events = read_sse(client, "run_1003", reviewer)
    assert events[-1]["type"] == "done" and events[-1]["data"]["status"] == "skipped"


def test_run_states_cover_non_happy_paths(client, reviewer):
    statuses = {r["status"] for r in client.get("/api/runs", headers=reviewer).json()["runs"]}
    assert {"awaiting_approval", "skipped", "submitted", "blocked", "dead_letter", "rejected", "needs_attention"} <= statuses


def test_trace_has_spans_cost_and_mcp_calls(client, reviewer):
    t = client.get("/api/runs/run_1001/trace", headers=reviewer).json()
    kinds = {s["kind"] for s in t["spans"]}
    assert {"graph", "node", "llm", "mcp"} <= kinds and t["total_cost_usd"] > 0


def test_approve_submits_and_moves_card_to_submitted(client, reviewer):
    res = client.post("/api/approvals/appr_1001/decision", headers=reviewer, json={"action": "approve"})
    assert res.status_code == 200 and res.json()["submitted"] is True and res.json()["connects_spent"] == 16
    board = client.get("/api/pipeline", headers=reviewer).json()
    submitted = next(c for c in board["columns"] if c["stage"] == "submitted")
    assert "job_1001" in [c["job_id"] for c in submitted["cards"]]
    assert client.get("/api/runs/run_1001", headers=reviewer).json()["summary"]["status"] == "submitted"


def test_edit_requires_text_reject_requires_reason(client, reviewer):
    assert client.post("/api/approvals/appr_1002/decision", headers=reviewer, json={"action": "edit"}).status_code == 422
    assert client.post("/api/approvals/appr_1002/decision", headers=reviewer, json={"action": "reject", "reason": "  "}).status_code == 422
    ok = client.post("/api/approvals/appr_1002/decision", headers=reviewer, json={"action": "edit", "edited_text": "Shorter letter."})
    assert ok.status_code == 200 and ok.json()["status"] == "edited"
    studio = client.get("/api/proposals/job_1002", headers=reviewer).json()
    assert studio["draft"]["cover_letter"] == "Shorter letter."


def test_pending_approval_survives_reload_and_studio_is_grounded(client, reviewer):
    for _ in range(2):  # "refresh": state comes from the server every time
        items = client.get("/api/approvals?status=pending", headers=reviewer).json()["approvals"]
        assert "appr_1001" in [a["approval_id"] for a in items]
    studio = client.get("/api/proposals/job_1001", headers=reviewer).json()
    letter = studio["draft"]["cover_letter"]
    for claim in studio["draft"]["claims"]:
        if not claim["removed"]:
            assert claim["text"] in letter, "claim text must be an exact substring so the UI can highlight it"
            assert claim["evidence_ids"], claim
    assert any(c["removed"] and c["label"] == "unsupported" for c in studio["draft"]["claims"])
    new = client.post("/api/proposals/job_1001/regenerate", headers=reviewer, json={"paragraph_index": 1}).json()
    assert new["draft"]["revision"] == studio["draft"]["revision"] + 1 and new["paragraphs"][1] != studio["paragraphs"][1]


def test_degraded_mode_flips_health_and_queues_sends(client, reviewer):
    assert client.get("/api/health").json()["marketplace"]["ok"] is True
    client.post("/api/_mock/degrade", json={"degraded": True})
    h = client.get("/api/health").json()
    assert h["marketplace"]["ok"] is False and h["status"] == "degraded"
    assert client.get("/api/jobs", headers=reviewer).json()["marketplace_degraded"] is True
    res = client.post("/api/approvals/appr_1001/decision", headers=reviewer, json={"action": "approve"}).json()
    assert res["queued"] is True and res["submitted"] is False
    client.post("/api/_mock/degrade", json={"degraded": False})
    assert client.get("/api/health").json()["marketplace"]["ok"] is True


def test_message_reply_requires_approval_then_sends(client, reviewer):
    thread = client.get("/api/messages/thr_2", headers=reviewer).json()
    assert thread["suggested_reply"] and len(thread["slots"]) == 3
    assert client.post("/api/messages/thr_2/decision", headers=reviewer, json={"action": "reject"}).status_code == 422
    res = client.post("/api/messages/thr_2/decision", headers=reviewer, json={"action": "approve", "slot_id": "slot_1"}).json()
    assert res["status"] == "sent" and res["interview_hold"]["slot_id"] == "slot_1"
    again = client.get("/api/messages/thr_2", headers=reviewer).json()
    assert again["suggested_reply"] is None and again["messages"][-1]["sender"] == "freelancer"


def test_injection_and_scam_fixtures_are_flagged(client, reviewer):
    jobs = {j["job_id"]: j for j in client.get("/api/jobs?include_skipped=true", headers=reviewer).json()["jobs"]}
    assert jobs["job_1003"]["is_scam"] and jobs["job_1004"]["injection_detected"]
    detail = client.get("/api/jobs/job_1004", headers=reviewer).json()
    assert detail["sanitized_notes"] and detail["risk"]["injection_detected"]
    assert client.get("/api/analytics", headers=reviewer).json()["is_sample"] is True
