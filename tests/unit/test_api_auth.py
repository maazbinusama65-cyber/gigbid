# ruff: noqa: F811
"""Auth, sessions, reviewer seed, trace id, PII masking."""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from apps.api.auth.passwords import hash_password, verify_password
from apps.api.db import SessionRow, UserRow, utcnow
from apps.api.logging_setup import install_logging, mask_pii

from .api_fixtures import (  # noqa: F401
    REVIEWER_EMAIL,
    REVIEWER_PASSWORD,
    app,
    auth,
    client,
    make_config,
    register,
    reviewer,
)


def test_register_login_me_roundtrip(client):
    reg = register(client, "New.User@Example.test")
    assert reg["user"]["email"] == "new.user@example.test"
    assert reg["user"]["onboarded"] is False
    r = client.post("/api/auth/login", json={"email": "new.user@example.test", "password": "correct horse battery"})
    assert r.status_code == 200
    me = client.get("/api/auth/me", headers=auth(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "new.user@example.test"


def test_duplicate_email_conflicts_and_bad_password_rejected(client):
    register(client, "dup@example.test")
    assert client.post("/api/auth/register", json={"email": "DUP@example.test", "password": "another-long-pass"}).status_code == 409
    assert client.post("/api/auth/register", json={"email": "x@example.test", "password": "short"}).status_code == 422
    bad = client.post("/api/auth/login", json={"email": "dup@example.test", "password": "wrong-password"})
    assert bad.status_code == 401
    assert client.post("/api/auth/login", json={"email": "nobody@example.test", "password": "whatever-1"}).status_code == 401


def test_passwords_and_tokens_are_stored_hashed(app, client):
    token = register(client, "hash@example.test", "my-secret-password")["access_token"]
    with app.state.session_factory() as db:
        user = db.execute(select(UserRow).where(UserRow.email == "hash@example.test")).scalar_one()
        assert user.password_hash.startswith("scrypt$") and "my-secret-password" not in user.password_hash
        rows = db.execute(select(SessionRow)).scalars().all()
        assert rows and all(token != r.token_hash and len(r.token_hash) == 64 for r in rows)
    assert verify_password("my-secret-password", user.password_hash)
    assert not verify_password("nope", user.password_hash)
    assert hash_password("x", 2**10) != hash_password("x", 2**10)  # per-user salt


def test_missing_invalid_and_expired_tokens_are_401(app, client):
    assert client.get("/api/jobs").status_code == 401
    assert client.get("/api/jobs", headers=auth("garbage")).status_code == 401
    token = register(client, "exp@example.test")["access_token"]
    with app.state.session_factory() as db:
        row = db.execute(select(SessionRow).order_by(SessionRow.created_at.desc())).scalars().first()
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 401


def test_logout_revokes_session(client):
    token = register(client, "out@example.test")["access_token"]
    assert client.post("/api/auth/logout", headers=auth(token)).status_code == 200
    assert client.get("/api/auth/me", headers=auth(token)).status_code == 401


def test_login_is_rate_limited_after_repeated_failures(app):
    from fastapi.testclient import TestClient

    from apps.api.main import create_app

    with TestClient(create_app(make_config(login_max_failures=3))) as c:
        for _ in range(3):
            assert c.post("/api/auth/login", json={"email": "rl@example.test", "password": "bad-password"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "rl@example.test", "password": "bad-password"}).status_code == 429


def test_reviewer_account_is_seeded_with_ai_ml_persona(client, reviewer):
    me = client.get("/api/auth/me", headers=reviewer).json()
    assert me["email"] == REVIEWER_EMAIL
    assert me["persona_id"] == "ai_ml" and me["onboarded"] is True
    assert REVIEWER_PASSWORD not in str(me)


def test_trace_id_is_minted_and_propagated(client):
    r = client.get("/api/health")
    assert len(r.headers["x-trace-id"]) >= 8
    r2 = client.get("/api/health", headers={"X-Trace-Id": "trace-abc12345"})
    assert r2.headers["x-trace-id"] == "trace-abc12345"
    bad = client.get("/api/health", headers={"X-Trace-Id": "bad id with spaces!"})
    assert bad.headers["x-trace-id"] != "bad id with spaces!"
    err = client.get("/api/jobs", headers={"X-Trace-Id": "trace-err-12345"})
    assert err.status_code == 401 and err.headers["x-trace-id"] == "trace-err-12345"
    assert err.json()["trace_id"] == "trace-err-12345"


def test_trace_id_reaches_the_run_record(client, reviewer):
    run = client.post("/api/jobs/job_1007/analyze", headers={**reviewer, "X-Trace-Id": "ui-trace-777777"}).json()
    detail = client.get(f"/api/runs/{run['run_id']}", headers=reviewer).json()
    assert detail["summary"]["trace_id"] == "ui-trace-777777"
    assert "ui-trace-777777" in detail["trace_url"]


def test_pii_masking_filter_masks_emails_phones_cards_and_tokens(caplog):
    assert "[email]" in mask_pii("contact jane.doe@example.com now")
    assert "[phone]" in mask_pii("call +1 415-555-0132 please")
    assert "[card]" in mask_pii("card 4111 1111 1111 1111 expires")
    assert "abcdef" not in mask_pii("Authorization: Bearer abcdef0123456789abcdef")
    assert "2026-11-12" in mask_pii("on 2026-11-12 at 10:30")
    install_logging()
    log = logging.getLogger("apps.api.pii-test")
    from apps.api.logging_setup import PiiMaskingFilter

    record = log.makeRecord("x", logging.INFO, "f", 1, "user %s paid with %s", ("a@b.example", "4111111111111111"), None)
    PiiMaskingFilter().filter(record)
    assert "a@b.example" not in record.getMessage() and "4111111111111111" not in record.getMessage()
