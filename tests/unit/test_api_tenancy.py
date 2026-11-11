# ruff: noqa: F811
"""Tenant isolation: one user can never read or change another user's data."""
from __future__ import annotations

from sqlalchemy import select

from apps.api.auth import token_store
from apps.api.auth.crypto import TokenCipher
from apps.api.db import OAuthTokenRow

from .api_fixtures import app, client, user_a, user_b  # noqa: F401

SECRET = "gigsim-oauth-access-token-SECRET-123"


def test_oauth_tokens_are_encrypted_at_rest_and_scoped_to_user(app, client, user_a, user_b):
    r = client.put("/api/settings/connections/gigsim", headers=user_a, json={"access_token": SECRET, "scopes": "read write"})
    assert r.status_code == 200
    assert SECRET not in r.text  # never echoed back
    conn = {c["provider"]: c for c in r.json()["connections"]}
    assert conn["gigsim"]["connected"] and not conn["upwork"]["connected"]

    other = {c["provider"]: c for c in client.get("/api/settings/connections", headers=user_b).json()["connections"]}
    assert not other["gigsim"]["connected"]

    with app.state.session_factory() as db:
        row = db.execute(select(OAuthTokenRow)).scalars().one()
        assert SECRET.encode() not in row.access_token_enc
        cipher = TokenCipher("unit-test-secret-key")
        assert cipher.decrypt(row.access_token_enc) == SECRET
        assert TokenCipher("a-different-key").decrypt(row.access_token_enc) is None
        # tenant-scoped accessors: another user id gets nothing
        assert token_store.get_access_token(db, cipher, "someone-else", "gigsim") is None
        assert token_store.list_connections(db, "someone-else") == []

    assert client.delete("/api/settings/connections/gigsim", headers=user_b).status_code == 200
    mine = {c["provider"]: c for c in client.get("/api/settings/connections", headers=user_a).json()["connections"]}
    assert mine["gigsim"]["connected"], "user B's disconnect must not touch user A's token"


def test_portfolio_files_are_per_user(client, user_a, user_b):
    up = client.post("/api/onboarding/portfolio", headers=user_a, files={"file": ("../../cv.md", b"# CV\nfive years of ML", "text/markdown")})
    assert up.status_code == 201
    assert up.json()["filename"] == "cv.md"  # path components stripped
    assert [f["filename"] for f in client.get("/api/onboarding/portfolio", headers=user_a).json()] == ["cv.md"]
    assert client.get("/api/onboarding/portfolio", headers=user_b).json() == []
    assert client.post("/api/onboarding/portfolio", headers=user_a, files={"file": ("evil.exe", b"MZ", "application/octet-stream")}).status_code == 422


def test_approvals_are_independent_per_user(client, user_a, user_b):
    body = {"action": "reject", "reason": "tone too formal"}
    assert client.post("/api/approvals/appr_1001/decision", headers=user_a, json=body).status_code == 200
    a = {x["approval_id"]: x["status"] for x in client.get("/api/approvals", headers=user_a).json()["approvals"]}
    b = {x["approval_id"]: x["status"] for x in client.get("/api/approvals", headers=user_b).json()["approvals"]}
    assert a["appr_1001"] == "rejected" and b["appr_1001"] == "pending"
    assert client.post("/api/approvals/appr_1001/decision", headers=user_a, json=body).status_code == 409


def test_runs_and_jobs_created_by_one_user_are_invisible_to_another(client, user_a, user_b):
    run_id = client.post("/api/jobs/job_1007/analyze", headers=user_a).json()["run_id"]
    assert client.get(f"/api/runs/{run_id}", headers=user_a).status_code == 200
    assert client.get(f"/api/runs/{run_id}", headers=user_b).status_code == 404
    assert client.get(f"/api/runs/{run_id}/trace", headers=user_b).status_code == 404
    assert client.get(f"/api/runs/{run_id}/stream", headers=user_b).status_code == 404
    assert run_id not in [r["run_id"] for r in client.get("/api/runs", headers=user_b).json()["runs"]]
    # job status is per user too
    client.post("/api/jobs/job_1006/skip", headers=user_a, json={"reason": "off-topic"})
    ids_a = [j["job_id"] for j in client.get("/api/jobs", headers=user_a).json()["jobs"]]
    ids_b = [j["job_id"] for j in client.get("/api/jobs", headers=user_b).json()["jobs"]]
    assert "job_1006" not in ids_a and "job_1006" in ids_b


def test_memory_deletion_and_settings_are_per_user(client, user_a, user_b):
    assert client.delete("/api/memory/mem_2", headers=user_a).status_code == 200
    assert "mem_2" not in [m["memory_id"] for m in client.get("/api/memory", headers=user_a).json()["items"]]
    assert "mem_2" in [m["memory_id"] for m in client.get("/api/memory", headers=user_b).json()["items"]]
    assert client.delete("/api/memory/mem_2", headers=user_a).status_code == 404
    client.put("/api/settings", headers=user_a, json={"autonomy_level": "manual", "weekly_connects_budget": 10})
    assert client.get("/api/settings", headers=user_b).json()["autonomy_level"] == "assist"
