"""Shared fixtures for the API tests (imported by test_api_*.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from apps.api.config import AppConfig  # noqa: E402
from apps.api.main import create_app  # noqa: E402

REVIEWER_EMAIL = "reviewer@example.test"
REVIEWER_PASSWORD = "reviewer-test-pass-1"  # test-only value, not a real credential


def make_config(**overrides) -> AppConfig:
    base = dict(
        database_url="sqlite://", services_mode="mock", mock_delay_ms=0, scrypt_n=2**10,
        reviewer_email=REVIEWER_EMAIL, reviewer_password=REVIEWER_PASSWORD, secret_key="unit-test-secret-key",
    )
    base.update(overrides)
    return AppConfig(**base)


@pytest.fixture()
def app():
    return create_app(make_config())


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def register(client: TestClient, email: str, password: str = "correct horse battery") -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": password, "display_name": "T"})
    assert r.status_code == 201, r.text
    return r.json()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def reviewer(client):
    r = client.post("/api/auth/login", json={"email": REVIEWER_EMAIL, "password": REVIEWER_PASSWORD})
    assert r.status_code == 200, r.text
    return auth(r.json()["access_token"])


@pytest.fixture()
def user_a(client):
    return auth(register(client, "alice@example.test")["access_token"])


@pytest.fixture()
def user_b(client):
    return auth(register(client, "bob@example.test")["access_token"])


def read_sse(client: TestClient, run_id: str, headers: dict[str, str]) -> list[dict]:
    events: list[dict] = []
    with client.stream("GET", f"/api/runs/{run_id}/stream", headers=headers) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
    return events
