"""Small sqlite store for what the web API needs on top of LangGraph checkpoints:
runs, per-job analysis summaries, approvals (so a page refresh never loses one), proposals for the
pipeline board and per-user settings. Every row carries ``user_id`` and every query filters on it.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
create table if not exists runs(run_id text primary key, user_id text not null, kind text, job_id text,
  title text, status text, started_at real, finished_at real, latency_ms integer default 0,
  total_tokens integer default 0, cost_usd real default 0, trace_id text, thread_id text);
create index if not exists runs_user on runs(user_id, started_at);
create table if not exists job_state(user_id text, job_id text, status text, run_id text, title text,
  category text, summary_json text, updated_at real, primary key(user_id, job_id));
create table if not exists approvals(approval_id text primary key, user_id text not null, run_id text,
  thread_id text, kind text, status text, created_at real, decided_at real, title text, request_json text,
  decision_json text);
create index if not exists approvals_user on approvals(user_id, status);
create table if not exists proposals(proposal_id text primary key, user_id text not null, job_id text,
  title text, category text, stage text, bid_amount real, connects_spent integer, updated_at real,
  last_event text, thread_id text, client_name text);
create table if not exists settings(user_id text primary key, json text);
create table if not exists cursor(user_id text primary key, last_event_id text);
create table if not exists rejections(id integer primary key autoincrement, user_id text, reason text, ts real);
"""


class RealStore:
    def __init__(self, path: str | Path):
        p = str(path)
        if p != ":memory:":
            Path(p).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(p, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._lock = threading.RLock()

    def run(self, sql: str, args: tuple = ()) -> None:
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    def all(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        rows = self.all(sql, args)
        return rows[0] if rows else None

    # -- runs --------------------------------------------------------------------------------
    def upsert_run(self, run_id: str, user_id: str, **f: Any) -> None:
        cur = self.one("select * from runs where run_id=? and user_id=?", (run_id, user_id)) or {}
        row = {"run_id": run_id, "user_id": user_id, "kind": "bid", "status": "running",
               "started_at": time.time(), **cur, **f}
        cols = ["run_id", "user_id", "kind", "job_id", "title", "status", "started_at", "finished_at",
                "latency_ms", "total_tokens", "cost_usd", "trace_id", "thread_id"]
        self.run(f"insert or replace into runs({','.join(cols)}) values({','.join('?' * len(cols))})",
                 tuple(row.get(c) for c in cols))

    def get_run(self, user_id: str, run_id: str) -> dict | None:
        return self.one("select * from runs where run_id=? and user_id=?", (run_id, user_id))

    def list_runs(self, user_id: str, limit: int = 100) -> list[dict]:
        return self.all("select * from runs where user_id=? order by started_at desc limit ?", (user_id, limit))

    # -- job state ---------------------------------------------------------------------------
    def set_job(self, user_id: str, job_id: str, status: str, run_id: str | None, title: str, category: str,
                summary: dict) -> None:
        self.run("insert or replace into job_state values (?,?,?,?,?,?,?,?)",
                 (user_id, job_id, status, run_id, title, category, json.dumps(summary, default=str), time.time()))

    def get_job(self, user_id: str, job_id: str) -> dict | None:
        r = self.one("select * from job_state where user_id=? and job_id=?", (user_id, job_id))
        if r:
            r["summary"] = json.loads(r.pop("summary_json") or "{}")
        return r

    def list_jobs(self, user_id: str) -> list[dict]:
        rows = self.all("select * from job_state where user_id=?", (user_id,))
        for r in rows:
            r["summary"] = json.loads(r.pop("summary_json") or "{}")
        return rows

    # -- approvals ---------------------------------------------------------------------------
    def put_approval(self, approval_id: str, user_id: str, run_id: str, thread_id: str, kind: str, title: str,
                     request: dict) -> None:
        self.run("insert or replace into approvals values (?,?,?,?,?,?,?,?,?,?,?)",
                 (approval_id, user_id, run_id, thread_id, kind, "pending", time.time(), None, title,
                  json.dumps(request, default=str), None))

    def get_approval(self, user_id: str, approval_id: str) -> dict | None:
        r = self.one("select * from approvals where approval_id=? and user_id=?", (approval_id, user_id))
        return self._ap(r) if r else None

    def list_approvals(self, user_id: str, status: str | None = None) -> list[dict]:
        sql, args = "select * from approvals where user_id=?", [user_id]
        if status:
            sql += " and status=?"
            args.append(status)
        return [self._ap(r) for r in self.all(sql + " order by created_at desc", tuple(args))]

    def decide_approval(self, approval_id: str, status: str, decision: dict) -> None:
        self.run("update approvals set status=?, decided_at=?, decision_json=? where approval_id=?",
                 (status, time.time(), json.dumps(decision, default=str), approval_id))

    @staticmethod
    def _ap(r: dict) -> dict:
        r["request"] = json.loads(r.pop("request_json") or "{}")
        r["decision"] = json.loads(r["decision_json"]) if r.get("decision_json") else None
        r.pop("decision_json", None)
        return r

    # -- proposals / events ------------------------------------------------------------------
    def put_proposal(self, user_id: str, proposal_id: str, **f: Any) -> None:
        cur = self.one("select * from proposals where proposal_id=? and user_id=?", (proposal_id, user_id)) or {}
        row = {"proposal_id": proposal_id, "user_id": user_id, "stage": "submitted", "connects_spent": 0,
               "updated_at": time.time(), **cur, **f}
        cols = ["proposal_id", "user_id", "job_id", "title", "category", "stage", "bid_amount", "connects_spent",
                "updated_at", "last_event", "thread_id", "client_name"]
        self.run(f"insert or replace into proposals({','.join(cols)}) values({','.join('?' * len(cols))})",
                 tuple(row.get(c) for c in cols))

    def list_proposals(self, user_id: str) -> list[dict]:
        return self.all("select * from proposals where user_id=? order by updated_at desc", (user_id,))

    def get_cursor(self, user_id: str) -> str | None:
        r = self.one("select last_event_id from cursor where user_id=?", (user_id,))
        return r["last_event_id"] if r else None

    def set_cursor(self, user_id: str, last: str) -> None:
        self.run("insert or replace into cursor values (?,?)", (user_id, str(last)))

    # -- settings / rejections ---------------------------------------------------------------
    def get_settings(self, user_id: str) -> dict | None:
        r = self.one("select json from settings where user_id=?", (user_id,))
        return json.loads(r["json"]) if r else None

    def put_settings(self, user_id: str, data: dict) -> None:
        self.run("insert or replace into settings values (?,?)", (user_id, json.dumps(data)))

    def add_rejection(self, user_id: str, reason: str) -> None:
        self.run("insert into rejections(user_id, reason, ts) values (?,?,?)", (user_id, reason, time.time()))

    def rejections(self, user_id: str) -> list[dict]:
        return self.all("select reason, count(*) as n from rejections where user_id=? group by reason order by n desc",
                        (user_id,))
