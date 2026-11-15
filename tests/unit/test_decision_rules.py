"""Decision node budget rules (found through the dev failure analysis: underpaid hourly jobs were bid on)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent.config_loader import load_config
from agent.nodes.decision import decide

CTX = SimpleNamespace(cfg=load_config(overrides={"models.profile": "stub"}))


def _state(budget: dict, rate: float = 45.0) -> dict:
    return {"fit_report": {"score": 0.9}, "risk_report": {"score": 0.1, "is_scam": False, "flags": []},
            "job": {"job_id": "j", "budget": budget},
            "settings": {"hourly_rate_usd": rate, "min_project_budget_usd": 250}}


@pytest.mark.asyncio
@pytest.mark.parametrize("budget,expected", [
    ({"type": "hourly", "min": 14, "max": 20}, "skip"),     # 0.44x the freelancer's rate
    ({"type": "hourly", "min": 30, "max": 35}, "skip"),     # 0.78x: still under 80%
    ({"type": "hourly", "min": 40, "max": 50}, "bid"),      # above the rate
    ({"type": "hourly", "min": 30, "max": 36}, "bid"),      # exactly 0.8x is allowed
    ({"type": "fixed", "min": 100, "max": 200}, "skip"),    # existing fixed-price floor still applies
    ({"type": "fixed", "min": 500, "max": 900}, "bid"),
])
async def test_budget_rules(budget: dict, expected: str) -> None:
    out = await decide(_state(budget), CTX)
    assert out["decision"]["decision"] == expected, out["decision"]["reasons"]


@pytest.mark.asyncio
async def test_underpaid_hourly_job_gives_a_reason() -> None:
    out = await decide(_state({"type": "hourly", "min": 14, "max": 20}), CTX)
    assert any("hourly rate" in r for r in out["decision"]["reasons"])


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["dead_letter", "needs_attention", "blocked"])
async def test_decision_never_turns_an_upstream_failure_into_a_skip(failure: str) -> None:
    state = {**_state({"type": "fixed", "min": 500, "max": 900}), "status": failure, "fit_report": {}}
    assert await decide(state, CTX) == {}          # the failure status is left untouched


def test_short_requirements_get_a_searchable_query() -> None:
    from agent.nodes.matcher import search_query

    assert search_query("R") != "R" and len(search_query("R")) >= 3
    assert search_query("Go").startswith("Go ")
    assert search_query("PostgreSQL") == "PostgreSQL"
