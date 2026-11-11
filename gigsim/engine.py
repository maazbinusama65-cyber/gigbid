"""GigSim engine: proposals, connects, messages, events and the simulated-time tick."""
from __future__ import annotations

import hashlib
import json
import threading

from . import simmodel
from .settings import Policy, Settings
from .store import START_TS, SeedData, StateStore, fresh_state, iso_ts, parse_ts


class ApiError(Exception):
    def __init__(self, status: int, error: str, detail: str = "", headers: dict | None = None, extra: dict | None = None):
        super().__init__(error)
        self.status, self.error, self.detail, self.headers, self.extra = status, error, detail, headers or {}, extra or {}


class Engine:
    def __init__(self, settings: Settings):
        self.s = settings
        self.lock = threading.RLock()
        self.seed_data = SeedData(settings.seed_dir, settings.extra_jobs)
        self.policy = Policy(settings.policy_path)
        self.store = StateStore(settings.state_path)
        self.state = self.store.load() or fresh_state(settings.seed, self.policy.data().get("initial_balance", 120))
        self.s.seed = self.state["seed"]

    # ---- helpers -------------------------------------------------------------------------
    def save(self) -> None:
        self.store.save(self.state)

    def reset(self, seed: int | None) -> dict:
        seed = self.s.seed if seed is None else seed
        self.s.seed = seed
        self.state = fresh_state(seed, self.policy.data().get("initial_balance", 120))
        self.save()
        return {"status": "reset", "seed": seed, "now": iso_ts(self.state["clock"])}

    def nid(self, kind: str, prefix: str, width: int = 5) -> str:
        c = self.state["counters"]
        c[kind] += 1
        return f"{prefix}-{c[kind]:0{width}d}"

    def fl(self, fid: str) -> dict:
        return self.state["freelancers"][fid]

    def job(self, job_id: str) -> dict:
        j = self.seed_data.jobs.get(job_id)
        if j is None or (j.get("kind") in ("stream", "dev") and parse_ts(j["posted_at"]) > self.state["clock"]):
            raise ApiError(404, "job_not_found", f"unknown job {job_id}")
        return j

    def emit(self, ts: int, etype: str, fid: str, proposal_id: str | None, thread_id: str | None) -> None:
        self.state["counters"]["event"] += 1
        self.state["events"].append({"event_id": self.state["counters"]["event"], "ts": iso_ts(ts), "type": etype,
                                     "proposal_id": proposal_id, "thread_id": thread_id, "freelancer_id": fid})

    def add_message(self, thread: dict, sender: str, body: str, ts: int) -> dict:
        m = {"message_id": self.nid("message", "msg"), "thread_id": thread["thread_id"], "sender": sender,
             "body": body, "ts": iso_ts(ts), "ts_epoch": ts}
        self.state["messages"].append(m)
        thread["last_message_at"] = m["ts"]
        thread["unread"] = thread.get("unread", 0) + (1 if sender == "client" else 0)
        return m

    # ---- connects ------------------------------------------------------------------------
    def connects(self, fid: str) -> dict:
        f = self.fl(fid)
        return {"balance": f["balance"], "weekly_allowance": self.policy.data().get("weekly_allowance", 80),
                "spent_this_week": f["spent_this_week"]}

    # ---- proposals -----------------------------------------------------------------------
    def public_proposal(self, p: dict) -> dict:
        return {k: v for k, v in p.items() if k not in ("plan", "status_ts")} | {"status_at": iso_ts(p["status_ts"])}

    def create_proposal(self, fid: str, body: dict) -> tuple[int, dict]:
        job = self.job(body["job_id"])
        letter = (body.get("cover_letter") or "").strip()
        if not letter:
            raise ApiError(422, "validation_error", "cover_letter is required")
        bid = float(body.get("bid_amount") or 0)
        if bid <= 0:
            raise ApiError(422, "validation_error", "bid_amount must be > 0")
        answers = [str(a) for a in body.get("screening_answers") or []]
        viol = self.policy.check(letter + "\n" + "\n".join(answers))
        cost = self.policy.cost(job)
        payload = {"job_id": job["job_id"], "freelancer_id": fid, "cover_letter": letter, "screening_answers": answers,
                   "bid_amount": bid, "connects_cost": cost, "policy_violations": viol}
        after = self.fl(fid)["balance"] - cost
        if body.get("dry_run"):
            return 200, {"proposal_id": None, "status": "preview", "connects_cost": cost, "balance_after": after,
                         "payload": payload}
        self._reject_if_violating(viol)
        dup = [p for p in self.state["proposals"].values()
               if p["freelancer_id"] == fid and p["job_id"] == job["job_id"] and p["status"] != "lost"]
        if dup:
            raise ApiError(409, "already_exists", f"proposal {dup[0]['proposal_id']} already exists for this job",
                           extra={"proposal_id": dup[0]["proposal_id"]})
        pid = self.nid("proposal", "prop")
        self.state["proposals"][pid] = {
            "proposal_id": pid, "freelancer_id": fid, "job_id": job["job_id"], "client_id": job["client_id"],
            "status": "draft", "status_ts": self.state["clock"], "cover_letter": letter, "screening_answers": answers,
            "bid_amount": bid, "connects_cost": cost, "created_at": iso_ts(self.state["clock"]), "submitted_at": None,
            "thread_id": None, "plan": None}
        self.save()
        return 201, {"proposal_id": pid, "status": "draft", "connects_cost": cost, "balance_after": after, "payload": payload}

    def _reject_if_violating(self, viol: list[dict]) -> None:
        hard = [v for v in viol if v["enforcement"] == "reject"]
        if hard:
            raise ApiError(422, "policy_violation", "; ".join(f"{v['rule_id']}: {v['description']}" for v in hard),
                           extra={"violations": hard})

    def get_proposal(self, fid: str, pid: str) -> dict:
        p = self.state["proposals"].get(pid)
        if not p or p["freelancer_id"] != fid:
            raise ApiError(404, "proposal_not_found", pid)
        return p

    def submit(self, fid: str, pid: str) -> tuple[int, dict]:
        p = self.get_proposal(fid, pid)
        if p["status"] != "draft":
            raise ApiError(409, "not_a_draft", f"proposal is {p['status']}")
        job = self.job(p["job_id"])
        self._reject_if_violating(self.policy.check(p["cover_letter"] + "\n" + "\n".join(p["screening_answers"])))
        cost = self.policy.cost(job)
        f = self.fl(fid)
        if f["balance"] < cost:
            raise ApiError(402, "insufficient_connects", f"need {cost}, have {f['balance']}",
                           extra={"balance": f["balance"], "connects_cost": cost})
        f["balance"] -= cost
        f["spent_this_week"] += cost
        now = self.state["clock"]
        p.update(status="submitted", status_ts=now, submitted_at=iso_ts(now), connects_cost=cost,
                 plan=simmodel.make_plan(self.state["seed"], fid, job, p["cover_letter"], p["screening_answers"],
                                         p["bid_amount"], self.s.decision_hook))
        self.save()
        return 200, {"proposal_id": pid, "status": "submitted", "connects_spent": cost, "balance": f["balance"]}

    # ---- threads / messages --------------------------------------------------------------
    def thread_for(self, fid: str, tid: str) -> dict:
        t = self.state["threads"].get(tid)
        if not t or t["freelancer_id"] != fid:
            raise ApiError(404, "thread_not_found", tid)
        return t

    def post_message(self, fid: str, tid: str, body: str) -> tuple[int, dict]:
        t = self.thread_for(fid, tid)
        if not body.strip():
            raise ApiError(422, "validation_error", "body is required")
        viol = self.policy.check(body)
        self._reject_if_violating([v for v in viol if v["type"] == "forbid_regex"])
        now = self.state["clock"]
        m = self.add_message(t, "freelancer", body, now)
        h = int(hashlib.sha256(f"{self.state['seed']}{m['message_id']}".encode()).hexdigest()[:6], 16)
        t["pending_reply_at"] = now + (1 + h % 4) * simmodel.HOUR
        t["pending_reply_to"] = m["message_id"]
        self.save()
        return 201, self.public_message(m)

    @staticmethod
    def public_message(m: dict) -> dict:
        return {k: v for k, v in m.items() if k != "ts_epoch"}

    @staticmethod
    def public_thread(t: dict) -> dict:
        return {k: v for k, v in t.items() if not k.startswith("pending")}

    # ---- simulated time ------------------------------------------------------------------
    def tick(self, steps: int) -> dict:
        now0 = self.state["clock"]
        now = now0 + steps * simmodel.HOUR
        pending: list[tuple[int, str, str, str]] = []  # (ts, kind, id, extra)
        week = (now - START_TS) // simmodel.WEEK
        while self.state["week"] < week:
            self.state["week"] += 1
            for fl in self.state["freelancers"].values():
                allow = self.policy.data().get("weekly_allowance", 80)
                fl["balance"] = min(fl["balance"] + allow, self.policy.data().get("max_balance", 300))
                fl["spent_this_week"] = 0
        for pid in sorted(self.state["proposals"]):
            p = self.state["proposals"][pid]
            if p["status"] in ("draft", "hired", "lost") or not p["plan"]:
                continue
            fl_ts = self._fl_msg_ts(p)
            for ts, new in simmodel.advance(p, p["plan"], fl_ts, now):
                pending.append((ts, "status", pid, new))
        for tid in sorted(self.state["threads"]):
            t = self.state["threads"][tid]
            if t.get("pending_reply_at") and t["pending_reply_at"] <= now:
                pending.append((t["pending_reply_at"], "reply", tid, ""))
        pending.sort(key=lambda x: (x[0], x[1], x[2]))
        for ts, kind, ident, new in pending:
            if kind == "status":
                self._apply_status(ts, ident, new)
            else:
                self._apply_reply(ts, ident)
        self.state["clock"] = now
        self.save()
        return {"now": iso_ts(now), "steps": steps, "events_emitted": len(pending),
                "proposals_changed": len({x[2] for x in pending if x[1] == "status"})}

    def _fl_msg_ts(self, p: dict) -> list[int]:
        tid = p.get("thread_id")
        if not tid:
            return []
        return sorted(m["ts_epoch"] for m in self.state["messages"] if m["thread_id"] == tid and m["sender"] == "freelancer")

    def _apply_status(self, ts: int, pid: str, new: str) -> None:
        p = self.state["proposals"][pid]
        job = self.seed_data.jobs[p["job_id"]]
        if new == "replied":
            tid = self.nid("thread", "thr", 4)
            self.state["threads"][tid] = {"thread_id": tid, "freelancer_id": p["freelancer_id"], "client_id": p["client_id"],
                                          "job_id": p["job_id"], "proposal_id": pid, "subject": job["title"],
                                          "created_at": iso_ts(ts), "last_message_at": iso_ts(ts), "unread": 0}
            p["thread_id"] = tid
        t = self.state["threads"].get(p.get("thread_id") or "")
        if t and new in ("replied", "interview", "hired", "lost"):
            self.add_message(t, "client", simmodel.client_message(new, job, p["plan"]), ts)
        self.emit(ts, new, p["freelancer_id"], pid, p.get("thread_id"))

    def _apply_reply(self, ts: int, tid: str) -> None:
        t = self.state["threads"][tid]
        src = next((m for m in self.state["messages"] if m["message_id"] == t.get("pending_reply_to")), None)
        self.add_message(t, "client", simmodel.auto_reply(src["body"] if src else ""), ts)
        t["pending_reply_at"] = None
        self.emit(ts, "message", t["freelancer_id"], t["proposal_id"], tid)

    # ---- pricing stats -------------------------------------------------------------------
    def market_stats(self, category: str | None, skills: list[str]) -> dict:
        sd = self.seed_data
        key = sd.category_key(category) if category else "All categories"
        if key is None:
            raise ApiError(404, "unknown_category", f"no stats for category {category!r}")
        base = {k: sd.stats[key].get(k) for k in ("n", "p10", "p25", "p50", "p75", "p90", "hourly_p50")}
        sk = []
        for s in skills:
            k = sd.stats_lc.get(f"skill:{s.strip().lower()}")
            row = {"skill": s.strip()}
            row.update({kk: sd.stats[k].get(kk) for kk in ("n", "p10", "p25", "p50", "p75", "p90", "hourly_p50")} if k else {"n": 0})
            sk.append(row)
        return {"category": key, **base, "skills": sk}

    def fingerprint(self, method: str, path: str, body: dict) -> str:
        return hashlib.sha256(f"{method}|{path}|{json.dumps(body, sort_keys=True)}".encode()).hexdigest()
