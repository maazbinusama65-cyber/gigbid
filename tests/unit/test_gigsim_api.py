"""GigSim REST contract: auth, idempotency, connects, dry_run, rate limit, errors, policy, ticks."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import httpx
import pytest

from gigsim import datagen
from gigsim.app import create_app
from gigsim.settings import PKG, Settings

TOKEN = "test-token"
FL = {"Authorization": f"Bearer {TOKEN}", "X-Freelancer-Id": "fullstack"}
GOOD_LETTER = ("Your point about the checkout flow is close to something I shipped for a retail client last year. "
               "I built it end to end and cut page load by 40%. " * 2 + "Happy to share a plan for the first week.")


@pytest.fixture(scope="module")
def seed_dir(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("seed")
    datagen.generate(1337, root, use_kaggle=False, n_dev=60, n_test=20, n_history=300, n_real=0)
    return root / "data" / "gigsim_seed"


@pytest.fixture
def policy_path(tmp_path) -> Path:
    p = tmp_path / "policy.json"
    shutil.copy(PKG / "policy.json", p)
    return p


def make_app(seed_dir, policy_path, tmp_path=None, **kw):
    s = Settings(token=TOKEN, seed_dir=seed_dir, policy_path=policy_path, state_path=kw.pop("state_path", ""),
                 rate_limit_rpm=kw.pop("rate_limit_rpm", 100000), **kw)
    return create_app(s)


def client(app, headers=FL):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gigsim", headers=headers)


async def first_job(c, i=0):
    return (await c.get("/v1/jobs?limit=50")).json()["jobs"][i]


async def draft(c, job_id, letter=GOOD_LETTER, bid=500, **extra):
    return await c.post("/v1/proposals", json={"job_id": job_id, "cover_letter": letter, "screening_answers": [],
                                               "bid_amount": bid, **extra})


@pytest.mark.asyncio
async def test_health_open_and_auth_required(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path)
    async with client(app, {}) as c:
        assert (await c.get("/health")).json() == {"status": "ok"}
        r = await c.get("/v1/jobs")
        assert r.status_code == 401 and r.json()["error"] == "unauthorized"
        r = await c.get("/v1/jobs", headers={"Authorization": "Bearer nope"})
        assert r.status_code == 401


@pytest.mark.asyncio
async def test_jobs_clients_stats_policy_shapes(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path)
    async with client(app) as c:
        page = (await c.get("/v1/jobs?limit=5")).json()
        assert len(page["jobs"]) == 5 and page["next_cursor"]
        nxt = (await c.get(f"/v1/jobs?limit=5&cursor={page['next_cursor']}")).json()
        assert {j["job_id"] for j in nxt["jobs"]}.isdisjoint({j["job_id"] for j in page["jobs"]})
        j = page["jobs"][0]
        assert set(j) == {"job_id", "client_id", "title", "description", "category", "required_skills", "budget",
                          "duration_days", "screening_questions", "posted_at", "connects_cost"}
        assert (await c.get(f"/v1/jobs/{j['job_id']}")).json() == j
        assert (await c.get("/v1/jobs/nope")).status_code == 404
        cl = (await c.get(f"/v1/clients/{j['client_id']}")).json()
        assert {"client_id", "name", "industry", "payment_verified", "total_spent", "hire_rate", "avg_rating",
                "jobs_posted", "member_since", "country", "history"} == set(cl)
        cat = (await c.get(f"/v1/jobs?category={j['category']}&limit=200")).json()["jobs"]
        assert cat and all(x["category"] == j["category"] for x in cat)
        sk = j["required_skills"][0]
        assert all(sk.lower() in [s.lower() for s in x["required_skills"]]
                   for x in (await c.get(f"/v1/jobs?skills={sk}&limit=200")).json()["jobs"])
        pol = (await c.get("/v1/policy")).json()
        assert {"version", "connects_per_proposal", "rules", "rate_limit_rpm"} <= set(pol)
        assert {r["type"] for r in pol["rules"]} >= {"forbid_regex", "max_words"}
        assert all({"id", "type", "description"} <= set(r) and ("pattern" in r or "value" in r) for r in pol["rules"])
        ms = (await c.get("/v1/market_stats?category=AI %26 Machine Learning&skills=Python,Celery")).json()
        assert {"category", "n", "p10", "p25", "p50", "p75", "p90", "hourly_p50", "skills"} <= set(ms)
        assert [s["skill"] for s in ms["skills"]] == ["Python", "Celery"]
        assert (await c.get("/v1/market_stats?category=nonsense")).status_code == 404


@pytest.mark.asyncio
async def test_dry_run_never_persists_and_draft_does_not_spend(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path)
    async with client(app) as c:
        job = await first_job(c)
        before = (await c.get("/v1/connects")).json()
        r = await draft(c, job["job_id"], dry_run=True)
        assert r.status_code == 200 and r.json()["status"] == "preview" and r.json()["proposal_id"] is None
        assert r.json()["balance_after"] == before["balance"] - r.json()["connects_cost"]
        assert (await c.get("/v1/proposals")).json()["proposals"] == []
        assert (await c.get("/v1/connects")).json() == before
        r = await draft(c, job["job_id"])
        assert r.status_code == 201 and r.json()["status"] == "draft"
        assert (await c.get("/v1/connects")).json()["balance"] == before["balance"]
        assert len((await c.get("/v1/proposals?status=draft")).json()["proposals"]) == 1
        assert (await draft(c, job["job_id"])).status_code == 409


@pytest.mark.asyncio
async def test_submit_requires_key_and_never_double_spends(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path)
    async with client(app) as c:
        job = await first_job(c)
        pid = (await draft(c, job["job_id"])).json()["proposal_id"]
        assert (await c.post(f"/v1/proposals/{pid}/submit")).status_code == 400
        start = (await c.get("/v1/connects")).json()["balance"]
        k = {"Idempotency-Key": "abc-1"}
        r1 = await c.post(f"/v1/proposals/{pid}/submit", headers=k)
        r2 = await c.post(f"/v1/proposals/{pid}/submit", headers=k)
        r3 = await c.post(f"/v1/proposals/{pid}/submit", headers=k)
        assert r1.status_code == 200 and r1.json() == r2.json() == r3.json()
        assert r2.headers["idempotent-replay"] == "true"
        cost = r1.json()["connects_spent"]
        assert (await c.get("/v1/connects")).json() == {"balance": start - cost, "weekly_allowance": 80, "spent_this_week": cost}
        r4 = await c.post(f"/v1/proposals/{pid}/submit", headers={"Idempotency-Key": "abc-2"})
        assert r4.status_code == 409  # already submitted: a new key cannot spend again
        assert (await c.get("/v1/connects")).json()["balance"] == start - cost
        # same key, different request -> rejected
        j2 = await first_job(c, 1)
        pid2 = (await draft(c, j2["job_id"])).json()["proposal_id"]
        r5 = await c.post(f"/v1/proposals/{pid2}/submit", headers=k)
        assert r5.status_code == 422 and r5.json()["error"] == "idempotency_key_reuse"
        assert (await c.get(f"/v1/proposals/{pid}")).json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_after_commit_error_then_retry_does_not_double_spend(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path, error_after_commit_rate=1.0)
    async with client(app) as c:
        job = await first_job(c)
        pid = (await draft(c, job["job_id"], dry_run=False)).json().get("proposal_id")
        if pid is None:  # the draft call itself may have been the one that "lost" its response
            pid = (await c.get("/v1/proposals")).json()["proposals"][0]["proposal_id"]
        start = (await c.get("/v1/connects")).json()["balance"]
        k = {"Idempotency-Key": "retry-me"}
        r1 = await c.post(f"/v1/proposals/{pid}/submit", headers=k)
        assert r1.status_code == 503
        assert (await c.get("/v1/connects")).json()["balance"] < start  # it did commit
        spent = start - (await c.get("/v1/connects")).json()["balance"]
        r2 = await c.post(f"/v1/proposals/{pid}/submit", headers=k)
        assert r2.status_code == 200 and r2.json()["connects_spent"] == spent
        assert (await c.get("/v1/connects")).json()["balance"] == start - spent


@pytest.mark.asyncio
async def test_insufficient_connects(seed_dir, policy_path):
    cfg = json.loads(policy_path.read_text())
    cfg["initial_balance"] = 5
    policy_path.write_text(json.dumps(cfg))
    app = make_app(seed_dir, policy_path)
    async with client(app) as c:
        pid = (await draft(c, (await first_job(c))["job_id"])).json()["proposal_id"]
        r = await c.post(f"/v1/proposals/{pid}/submit", headers={"Idempotency-Key": "x"})
        assert r.status_code == 402 and r.json()["error"] == "insufficient_connects"


@pytest.mark.asyncio
async def test_rate_limit_429_with_retry_after(seed_dir, policy_path):
    t = [0.0]
    app = make_app(seed_dir, policy_path, rate_limit_rpm=5, clock_fn=lambda: t[0])
    async with client(app) as c:
        codes = [(await c.get("/v1/connects")).status_code for _ in range(5)]
        assert codes == [200] * 5
        r = await c.get("/v1/connects")
        assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1 and r.json()["error"] == "rate_limited"
        # per user: another freelancer is not throttled
        assert (await c.get("/v1/connects", headers={**FL, "X-Freelancer-Id": "ai_ml"})).status_code == 200
        t[0] += 61
        assert (await c.get("/v1/connects")).status_code == 200
        assert (await c.get("/health")).status_code == 200


@pytest.mark.asyncio
async def test_error_injection_and_json_errors(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path, error_rate=1.0)
    async with client(app) as c:
        r = await c.get("/v1/connects")
        assert r.status_code == 503 and set(r.json()) >= {"error", "detail"}
        assert (await c.get("/health")).status_code == 200
    app = make_app(seed_dir, policy_path)
    async with client(app, {"Authorization": f"Bearer {TOKEN}"}) as c:
        r = await c.get("/v1/connects")
        assert r.status_code == 400 and r.json()["error"] == "missing_freelancer_id"
        r = await c.post("/v1/proposals", json={"job_id": "x"})
        assert r.status_code == 422 and r.json()["error"] == "validation_error"


@pytest.mark.asyncio
async def test_policy_is_a_pure_data_edit(seed_dir, policy_path):
    app = make_app(seed_dir, policy_path)
    async with client(app) as c:
        job = await first_job(c)
        bad = GOOD_LETTER + " Please message me on WhatsApp to continue."
        r = await draft(c, job["job_id"], bad)
        assert r.status_code == 422 and r.json()["error"] == "policy_violation"
        assert r.json()["violations"][0]["rule_id"] == "R1"
        assert (await draft(c, job["job_id"], bad, dry_run=True)).json()["payload"]["policy_violations"]
        cfg = json.loads(policy_path.read_text())
        cfg["version"] = 2
        for rule in cfg["rules"]:
            if rule["type"] == "connects_cost":
                rule.update(enabled=True, value=3)
            if rule["type"] == "max_words":
                rule["value"] = 20
        policy_path.write_text(json.dumps(cfg))
        os.utime(policy_path, (1e9 + 5, 1e9 + 5))
        pol = (await c.get("/v1/policy")).json()
        assert pol["version"] == 2 and pol["connects_per_proposal"] == 3
        r = await draft(c, job["job_id"], dry_run=True)
        assert r.json()["connects_cost"] == 3
        assert [v["rule_id"] for v in r.json()["payload"]["policy_violations"]] == ["R3"]


@pytest.mark.asyncio
async def test_state_persists_across_restart_and_reset(seed_dir, policy_path, tmp_path):
    sp = str(tmp_path / "state.json")
    app = make_app(seed_dir, policy_path, state_path=sp)
    async with client(app) as c:
        pid = (await draft(c, (await first_job(c))["job_id"])).json()["proposal_id"]
        await c.post(f"/v1/proposals/{pid}/submit", headers={"Idempotency-Key": "p1"})
        bal = (await c.get("/v1/connects")).json()["balance"]
        await c.post("/v1/sim/tick", json={"steps": 5})
    app2 = make_app(seed_dir, policy_path, state_path=sp)
    async with client(app2) as c:
        assert (await c.get("/v1/connects")).json()["balance"] == bal
        assert (await c.get(f"/v1/proposals/{pid}")).json()["status"] in ("submitted", "viewed", "lost")
        assert (await c.post("/v1/sim/reset", json={"seed": 99})).json()["seed"] == 99
        assert (await c.get("/v1/proposals")).json()["proposals"] == []
        assert (await c.get("/v1/connects")).json()["balance"] == 120


def specific_letter(job: dict) -> str:
    skills = ", ".join(job["required_skills"])
    return (f"Your brief asks for {skills}, and I shipped almost exactly that for a similar client last year. "
            f"I built it end to end and the result was 38% faster delivery and 12 fewer incidents. "
            f"For this job I would start with a short plan, then a first demo within five days.")


GENERIC_LETTER = ("Hello, I am writing to express my interest in your job posting. I am a hardworking professional "
                  "with many years of experience in various technologies and I think I am a good fit for this role.")


async def run_cohort(seed_dir, policy_path, seed: int):
    cfg = json.loads(policy_path.read_text())
    cfg["initial_balance"] = 10**6
    cfg["max_balance"] = 10**7
    policy_path.write_text(json.dumps(cfg))
    app = make_app(seed_dir, policy_path, seed=seed)
    async with client(app, {"Authorization": f"Bearer {TOKEN}"}) as c:
        jobs = [j for j in (await c.get("/v1/jobs?limit=200", headers=FL)).json()["jobs"] if j["budget"]["max"] > 0][:120]
        sent = {"ai_ml": 0, "fullstack": 0}
        for who, letter_fn, ratio in (("ai_ml", specific_letter, 0.8), ("fullstack", lambda j: GENERIC_LETTER, 1.5)):
            h = {**FL, "X-Freelancer-Id": who}
            for j in jobs:
                r = await c.post("/v1/proposals", headers=h, json={
                    "job_id": j["job_id"], "cover_letter": letter_fn(j), "screening_answers": ["Yes, details: " + "x" * 30] * len(j["screening_questions"]),
                    "bid_amount": j["budget"]["max"] * ratio})
                assert r.status_code == 201, r.text
                s = await c.post(f"/v1/proposals/{r.json()['proposal_id']}/submit", headers={**h, "Idempotency-Key": f"{who}-{j['job_id']}"})
                assert s.status_code == 200
                sent[who] += 1
        await c.post("/v1/sim/tick", json={"steps": 24 * 12})
        out = {}
        for who in sent:
            ev = (await c.get("/v1/events", headers={**FL, "X-Freelancer-Id": who})).json()
            replied = {e["proposal_id"] for e in ev if e["type"] == "replied"}
            out[who] = len(replied) / sent[who]
        evs = (await c.get("/v1/events?since=0", headers=FL)).json()
        return out, evs


@pytest.mark.asyncio
async def test_clients_reward_specific_grounded_proposals(seed_dir, policy_path):
    rates, _ = await run_cohort(seed_dir, policy_path, 1337)
    assert rates["ai_ml"] > rates["fullstack"] + 0.3, rates
    assert rates["fullstack"] < 0.2, rates


@pytest.mark.asyncio
async def test_simulation_is_deterministic_given_seed(seed_dir, policy_path):
    a = await run_cohort(seed_dir, policy_path, 5)
    b = await run_cohort(seed_dir, policy_path, 5)
    assert a == b


@pytest.mark.asyncio
async def test_reply_thread_messages_and_interview_gate(seed_dir, policy_path):
    cfg = json.loads(policy_path.read_text())
    cfg["initial_balance"] = 10**6
    policy_path.write_text(json.dumps(cfg))
    app = make_app(seed_dir, policy_path)
    async with client(app) as c:
        jobs = (await c.get("/v1/jobs?limit=200")).json()["jobs"]
        for j in jobs[:60]:
            r = await draft(c, j["job_id"], specific_letter(j), bid=j["budget"]["max"] * 0.8)
            await c.post(f"/v1/proposals/{r.json()['proposal_id']}/submit", headers={"Idempotency-Key": "k" + j["job_id"]})
        await c.post("/v1/sim/tick", json={"steps": 24 * 2})
        threads = (await c.get("/v1/threads")).json()["threads"]
        assert threads
        t = threads[0]
        msgs = (await c.get(f"/v1/messages?thread_id={t['thread_id']}")).json()["messages"]
        assert msgs[0]["sender"] == "client"
        prop = (await c.get(f"/v1/proposals/{t['proposal_id']}")).json()
        assert prop["status"] == "replied"  # waits for the freelancer: no interview without a message
        assert (await c.post("/v1/messages", json={"thread_id": t["thread_id"], "body": "I am available Tuesday for a call."})).status_code == 400
        h = {"Idempotency-Key": "m1"}
        r = await c.post("/v1/messages", json={"thread_id": t["thread_id"], "body": "I am available Tuesday for a call."}, headers=h)
        assert r.status_code == 201
        r2 = await c.post("/v1/messages", json={"thread_id": t["thread_id"], "body": "I am available Tuesday for a call."}, headers=h)
        assert r2.json() == r.json()
        assert len((await c.get(f"/v1/messages?thread_id={t['thread_id']}")).json()["messages"]) == len(msgs) + 1
        await c.post("/v1/sim/tick", json={"steps": 24 * 10})
        types = [e["type"] for e in (await c.get("/v1/events")).json()]
        assert "message" in types
        later = (await c.get(f"/v1/proposals/{t['proposal_id']}")).json()["status"]
        assert later in ("interview", "hired", "lost")
        last = (await c.get("/v1/events")).json()[-1]["event_id"]
        assert (await c.get(f"/v1/events?since={last}")).json() == []
        other = await c.get(f"/v1/messages?thread_id={t['thread_id']}", headers={**FL, "X-Freelancer-Id": "ai_ml"})
        assert other.status_code == 404  # threads are private to their freelancer
