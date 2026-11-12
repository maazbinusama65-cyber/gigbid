"""The web API driven by RealServices against a real GigSim process, the MCP servers (in-memory transport),
real retrieval and the LangGraph graphs (stub LLM): inbox -> analyse -> approval -> approve -> pipeline."""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from apps.api.config import AppConfig
from apps.api.main import create_app
from apps.api.real_services import RealServices
from apps.api.real_store import RealStore
from evals.harness import eval_env

EMAIL, PASSWORD = "real-reviewer@example.test", "real-reviewer-pass-1"   # test-only values

pytestmark = pytest.mark.skipif(os.getenv("SKIP_REAL_API") == "1", reason="needs GigSim subprocess + models")


async def _wait_run(c: httpx.AsyncClient, h: dict, run_id: str, want: set[str], timeout: float = 240) -> dict:
    for _ in range(int(timeout / 0.5)):
        r = (await c.get(f"/api/runs/{run_id}", headers=h)).json()
        if r["summary"]["status"] in want:
            return r
        await asyncio.sleep(0.5)
    raise AssertionError(f"run {run_id} did not reach {want}: {r}")


@pytest.mark.asyncio
async def test_inbox_to_approved_proposal_to_pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite"))
    monkeypatch.setenv("DATABASE_URL", "")
    async with eval_env("stub", "ai_ml", tmp=tmp_path):
        from agent.config_loader import load_config

        cfg = load_config(overrides={"models.profile": "stub"})
        svc = RealServices(cfg, RealStore(":memory:"))
        app = create_app(AppConfig(database_url="sqlite://", services_mode="real", scrypt_n=2**10, secret_key="k" * 24,
                                   reviewer_email=EMAIL, reviewer_password=PASSWORD), services=svc)
        transport = httpx.ASGITransport(app=app)
        async with app.router.lifespan_context(app), httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            tok = (await c.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD})).json()["access_token"]
            h = {"Authorization": f"Bearer {tok}"}
            health = (await c.get("/api/health")).json()
            assert health["marketplace"]["ok"] is True
            jobs = (await c.get("/api/jobs", headers=h)).json()
            assert jobs["total"] > 0 and not jobs["marketplace_degraded"]
            job_id = "dev-ai_ml-0070"          # a gold-"bid" job for this persona (deterministic seed data)
            detail = await c.get(f"/api/jobs/{job_id}", headers=h)
            assert detail.status_code == 200 and detail.json()["job"]["job_id"] == job_id
            r = await c.post(f"/api/jobs/{job_id}/analyze", headers=h)
            assert r.status_code == 202
            run_id = r.json()["run_id"]
            run = await _wait_run(c, h, run_id, {"awaiting_approval", "skipped", "blocked", "dead_letter", "needs_attention"})
            assert run["summary"]["status"] == "awaiting_approval", run
            assert any(s["node"] == "fit_matcher" for s in run["steps"])
            approvals = (await c.get("/api/approvals", headers=h)).json()
            assert approvals["pending_count"] == 1
            ap = approvals["approvals"][0]
            assert ap["request"]["dry_run"]["connects_cost"] > 0 and ap["request"]["draft"]["evidence_ids"]
            # refresh safety: the pending approval is served again from storage
            assert (await c.get("/api/approvals?status=pending", headers=h)).json()["pending_count"] == 1
            d = await c.post(f"/api/approvals/{ap['approval_id']}/decision", headers=h, json={"action": "approve"})
            assert d.status_code == 200 and d.json()["submitted"] is True, d.text
            again = await c.post(f"/api/approvals/{ap['approval_id']}/decision", headers=h, json={"action": "approve"})
            assert again.json()["message"] == "already decided"
            board = (await c.get("/api/pipeline", headers=h)).json()
            cards = [card for col in board["columns"] for card in col["cards"]]
            assert any(card["stage"] == "submitted" for card in cards)
            trace = (await c.get(f"/api/runs/{run_id}/trace", headers=h)).json()
            assert any(sp["kind"] == "mcp" for sp in trace["spans"])
            # another tenant cannot see this run
            await c.post("/api/auth/register", json={"email": "other@example.test", "password": "other-pass-12345", "display_name": "O"})
            tok2 = (await c.post("/api/auth/login", json={"email": "other@example.test", "password": "other-pass-12345"})).json()["access_token"]
            assert (await c.get(f"/api/runs/{run_id}", headers={"Authorization": f"Bearer {tok2}"})).status_code == 404
