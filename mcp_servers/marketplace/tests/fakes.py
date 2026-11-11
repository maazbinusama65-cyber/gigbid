"""In-memory stand-in for a marketplace adapter. Deliberately does NOT dedupe by key, so tests
prove the MCP server's own idempotency layer prevents double sends/spends."""
from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

from mcp_servers.marketplace.adapters.base import AdapterError

JOBS = {
    "job-1": {"job_id": "job-1", "client_id": "cl-1", "title": "Churn model", "description": "Build churn model",
              "category": "ml", "required_skills": ["Python", "scikit-learn"],
              "budget": {"type": "fixed", "min": 300, "max": 500, "currency": "USD"},
              "duration_days": 14, "screening_questions": ["How do you evaluate?"],
              "posted_at": "2026-01-02T00:00:00Z", "connects_cost": 8},
    "job-2": {"job_id": "job-2", "client_id": "cl-2", "title": "Dashboard", "description": "Build dashboard",
              "category": "analytics", "required_skills": ["SQL"], "budget": {"type": "hourly", "min": 20, "max": 40},
              "duration_days": 5, "screening_questions": [], "posted_at": "2026-01-03T00:00:00Z",
              "connects_cost": 6},
}


class FakeMarketplace:
    name = "fake"

    def __init__(self, balance: int = 100) -> None:
        self.balances: dict[str, int] = {}
        self.default_balance = balance
        self.calls: Counter[str] = Counter()
        self.users_seen: list[str] = []
        self.proposals: dict[str, dict[str, Any]] = {}
        self.messages: list[dict[str, Any]] = []
        self._ids = itertools.count(1)
        self.fail_next: AdapterError | None = None

    def _hit(self, name: str, user: str) -> None:
        self.calls[name] += 1
        self.users_seen.append(user)
        if self.fail_next:
            err, self.fail_next = self.fail_next, None
            raise err

    def _bal(self, user: str) -> int:
        return self.balances.setdefault(user, self.default_balance)

    async def search_jobs(self, user, *, q=None, category=None, skills=None, since=None, limit=20, cursor=None):
        self._hit("search_jobs", user)
        jobs = [j for j in JOBS.values()
                if (not q or q.lower() in (j["title"] + j["description"]).lower())
                and (not category or j["category"] == category)]
        return {"jobs": jobs[:limit], "next_cursor": None}

    async def get_job(self, user, job_id):
        self._hit("get_job", user)
        if job_id not in JOBS:
            raise AdapterError("not_found", f"job {job_id}")
        return JOBS[job_id]

    async def get_client(self, user, client_id):
        self._hit("get_client", user)
        return {"client_id": client_id, "name": "Acme", "payment_verified": True, "hire_rate": 0.6,
                "history": [{"job_id": "x", "title": "t", "outcome": "hired", "paid": 400, "feedback": "ok"}]}

    async def get_connects(self, user):
        self._hit("get_connects", user)
        return {"balance": self._bal(user), "weekly_allowance": 80, "spent_this_week": 0}

    async def get_market_stats(self, user, category=None, skills=None):
        self._hit("get_market_stats", user)
        return {category or "all": {"n": 40, "p10": 100, "p50": 350, "p90": 900, "hourly_p50": 35}}

    async def get_policy(self, user):
        self._hit("get_policy", user)
        return {"version": "2026.1", "connects_per_proposal": 8, "rate_limit_rpm": 60,
                "rules": [{"id": "no-offsite", "type": "forbidden_pattern", "pattern": "whatsapp|telegram",
                           "description": "No off-platform contact"}]}

    async def list_messages(self, user, thread_id=None):
        self._hit("list_messages", user)
        if thread_id:
            return {"thread_id": thread_id, "messages": [m for m in self.messages if m["thread_id"] == thread_id]}
        return {"threads": [{"thread_id": "t1", "client_id": "cl-1"}]}

    async def list_events(self, user, since=None):
        self._hit("list_events", user)
        return [{"event_id": 1, "ts": "2026-01-04T00:00:00Z", "type": "viewed", "proposal_id": "P1"},
                {"event_id": 2, "ts": "2026-01-04T01:00:00Z", "type": "replied", "proposal_id": "P1",
                 "thread_id": "t1"}]

    async def get_proposal(self, user, proposal_id):
        self._hit("get_proposal", user)
        if proposal_id not in self.proposals:
            raise AdapterError("not_found", f"proposal {proposal_id}")
        return self.proposals[proposal_id]

    async def create_proposal(self, user, payload, idempotency_key, dry_run):
        self._hit("create_proposal", user)
        cost = JOBS.get(payload["job_id"], {}).get("connects_cost", 8)
        if dry_run:
            return {"proposal_id": None, "status": "preview", "connects_cost": cost,
                    "balance_after": self._bal(user) - cost, "payload": payload}
        pid = f"P{next(self._ids)}"
        self.proposals[pid] = {**payload, "proposal_id": pid, "status": "draft", "owner": user,
                               "connects_cost": cost}
        return {"proposal_id": pid, "status": "draft", "connects_cost": cost,
                "balance_after": self._bal(user), "payload": payload}

    async def submit_proposal(self, user, proposal_id, idempotency_key):
        self._hit("submit_proposal", user)
        p = self.proposals[proposal_id]
        self.balances[user] = self._bal(user) - p["connects_cost"]
        p["status"] = "submitted"
        return {"proposal_id": proposal_id, "status": "submitted", "connects_spent": p["connects_cost"],
                "balance": self.balances[user]}

    async def send_message(self, user, thread_id, body, idempotency_key):
        self._hit("send_message", user)
        m = {"message_id": f"M{next(self._ids)}", "thread_id": thread_id, "body": body}
        self.messages.append(m)
        return m

    async def aclose(self):
        pass
