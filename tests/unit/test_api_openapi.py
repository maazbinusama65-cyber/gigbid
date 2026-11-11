# ruff: noqa: F811
"""The OpenAPI document is the web client's contract: it must be clean and exportable."""
from __future__ import annotations

import json

from .api_fixtures import ROOT, app  # noqa: F401

REQUIRED_PATHS = [
    "/api/auth/register", "/api/auth/login", "/api/auth/me", "/api/jobs", "/api/jobs/{job_id}",
    "/api/jobs/{job_id}/analyze", "/api/jobs/{job_id}/skip", "/api/proposals/{job_id}", "/api/approvals",
    "/api/approvals/{approval_id}/decision", "/api/pipeline", "/api/messages", "/api/runs", "/api/runs/{run_id}",
    "/api/runs/{run_id}/stream", "/api/runs/{run_id}/trace", "/api/analytics", "/api/settings", "/api/memory",
    "/api/memory/{memory_id}", "/api/onboarding", "/api/onboarding/portfolio", "/api/health",
]


def test_operation_ids_are_unique_function_names(app):
    schema = app.openapi()
    ids = []
    for path, ops in schema["paths"].items():
        for method, op in ops.items():
            ids.append(op["operationId"])
            assert "_" in op["operationId"] or op["operationId"].islower()
            assert not op["operationId"].endswith(method), f"auto-generated id on {method} {path}"
    assert len(ids) == len(set(ids))
    assert {"list_jobs", "decide_approval", "stream_run", "get_proposal_studio"} <= set(ids)


def test_required_routes_present_and_mock_controls_hidden(app):
    paths = app.openapi()["paths"]
    for p in REQUIRED_PATHS:
        assert p in paths, p
    assert not any("_mock" in p for p in paths)


def test_export_openapi_writes_file(tmp_path, monkeypatch):
    import subprocess
    import sys

    out = tmp_path / "openapi.json"
    res = subprocess.run([sys.executable, "-m", "apps.api.export_openapi", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["openapi"].startswith("3.") and "/api/runs/{run_id}/stream" in doc["paths"]
    run_status = doc["components"]["schemas"]["RunSummary"]["properties"]["status"]["enum"]
    assert {"running", "awaiting_approval", "submitted", "skipped", "rejected", "blocked", "needs_attention", "dead_letter"} == set(run_status)
