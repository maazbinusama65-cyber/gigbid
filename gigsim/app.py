"""GigSim REST app (stand-in marketplace). Run: python -m gigsim  (port 8081)."""
from __future__ import annotations

import math
import random
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .catalog_projects import PERSONA_IDS
from .catalog_skills import CATEGORIES
from .engine import ApiError, Engine
from .settings import Settings
from .store import SeedData, iso_ts, parse_ts

NO_AUTH = {"/health", "/docs", "/openapi.json", "/redoc"}
UNLIMITED_PREFIX = ("/v1/sim/",)


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    bid_amount: float
    dry_run: bool = False


class MessageIn(BaseModel):
    thread_id: str
    body: str


class TickIn(BaseModel):
    steps: int = Field(default=1, ge=1, le=24 * 365)


class ResetIn(BaseModel):
    seed: int | None = None


def _err(status: int, error: str, detail: str = "", headers=None, extra=None) -> JSONResponse:
    return JSONResponse({"error": error, "detail": detail, **(extra or {})}, status_code=status, headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    eng = Engine(s)
    app = FastAPI(title="GigSim (stand-in marketplace)", version="1.0")
    app.state.engine = eng
    hits: dict[str, deque] = defaultdict(deque)
    chaos = random.Random(f"{s.seed}:chaos")
    clock = s.clock_fn or time.monotonic

    def rpm() -> int:
        return s.rate_limit_rpm if s.rate_limit_rpm is not None else eng.policy.rate_limit_rpm()

    @app.exception_handler(ApiError)
    async def _api_error(_r: Request, e: ApiError):
        return _err(e.status, e.error, e.detail, e.headers, e.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, e: RequestValidationError):
        return _err(422, "validation_error", "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()))

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path in NO_AUTH:
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {s.token}":
            return _err(401, "unauthorized", "missing or invalid bearer token", {"WWW-Authenticate": "Bearer"})
        if path.startswith(UNLIMITED_PREFIX):
            return await call_next(request)
        who = request.headers.get("x-freelancer-id") or "anon"
        now, q = clock(), hits[who]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= rpm():
            wait = max(1, math.ceil(60 - (now - q[0])))
            return _err(429, "rate_limited", f"limit is {rpm()} requests per minute", {"Retry-After": str(wait)})
        q.append(now)
        if s.error_rate > 0 and chaos.random() < s.error_rate:
            return _err(503, "injected_failure", "simulated upstream error (GIGSIM_ERROR_RATE)")
        return await call_next(request)

    def fid_of(request: Request) -> str:
        f = request.headers.get("x-freelancer-id")
        if not f:
            raise ApiError(400, "missing_freelancer_id", "X-Freelancer-Id header is required")
        if f not in PERSONA_IDS:
            raise ApiError(404, "unknown_freelancer", f"known: {', '.join(PERSONA_IDS)}")
        return f

    def idempotent(request: Request, fid: str, body: dict, fn, required: bool):
        """Run fn() -> (status, body) once per Idempotency-Key; replays return the stored response."""
        key = request.headers.get("idempotency-key")
        if not key:
            if required and s.require_idempotency:
                raise ApiError(400, "idempotency_key_required", "send an Idempotency-Key header on this POST")
            status, out = fn()
            return JSONResponse(out, status_code=status)
        fp = eng.fingerprint(request.method, request.url.path, body)
        store = eng.state["idempotency"].setdefault(fid, {})
        rec = store.get(key)
        if rec:
            if rec["fp"] != fp:
                raise ApiError(422, "idempotency_key_reuse", "this Idempotency-Key was used with a different request")
            return JSONResponse(rec["body"], status_code=rec["status"], headers={"Idempotent-Replay": "true"})
        status, out = fn()
        store[key] = {"fp": fp, "status": status, "body": out}
        eng.save()
        if s.error_after_commit_rate > 0 and chaos.random() < s.error_after_commit_rate:
            raise ApiError(503, "injected_failure_after_commit", "committed, but the response was lost; retry with the same key")
        return JSONResponse(out, status_code=status)

    # ---- public ------------------------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/jobs")
    def list_jobs(q: str | None = None, category: str | None = None, skills: str | None = None,
                  since: str | None = None, limit: int = 50, cursor: str | None = None, kind: str | None = None):
        with eng.lock:
            if kind == "history":
                rows = [j for j in eng.seed_data.jobs.values() if j.get("kind") == "history"]
                rows.sort(key=lambda r: (r["posted_at"], r["job_id"]), reverse=True)
            else:
                nowiso = iso_ts(eng.state["clock"])
                rows = [j for j in eng.seed_data.open_jobs if j["posted_at"] <= nowiso]
            if q:
                toks = [t for t in q.lower().split() if t]
                rows = [j for j in rows if all(t in (j["title"] + " " + j["description"]).lower() for t in toks)]
            if category:
                c = category.strip().lower()
                c = CATEGORIES.get(c, c).lower()
                rows = [j for j in rows if j["category"].lower() == c]
            if skills:
                want = {x.strip().lower() for x in skills.split(",") if x.strip()}
                rows = [j for j in rows if want & {x.lower() for x in j["required_skills"]}]
            if since:
                try:
                    st = parse_ts(since)
                except ValueError as e:
                    raise ApiError(422, "validation_error", "since must be ISO-8601") from e
                rows = [j for j in rows if parse_ts(j["posted_at"]) >= st]
            limit = max(1, min(200, limit))
            try:
                off = int(cursor) if cursor else 0
            except ValueError as e:
                raise ApiError(422, "validation_error", "bad cursor") from e
            page = rows[off:off + limit]
            nxt = str(off + limit) if off + limit < len(rows) else None
            return {"jobs": [SeedData.public_job(j) for j in page], "next_cursor": nxt}

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str):
        with eng.lock:
            return SeedData.public_job(eng.job(job_id))

    @app.get("/v1/clients/{client_id}")
    def get_client(client_id: str):
        c = eng.seed_data.clients.get(client_id)
        if not c:
            raise ApiError(404, "client_not_found", client_id)
        return eng.seed_data.public_client(c)

    @app.get("/v1/policy")
    def policy():
        return eng.policy.public(rpm())

    @app.get("/v1/market_stats")
    def market_stats(category: str | None = None, skills: str | None = None):
        return eng.market_stats(category, [x for x in (skills or "").split(",") if x.strip()])

    # ---- freelancer-scoped -------------------------------------------------------------------
    @app.get("/v1/connects")
    def connects(request: Request):
        with eng.lock:
            return eng.connects(fid_of(request))

    @app.post("/v1/proposals")
    def create_proposal(request: Request, body: ProposalIn):
        fid = fid_of(request)
        with eng.lock:
            if body.dry_run:
                st, out = eng.create_proposal(fid, body.model_dump())
                return JSONResponse(out, status_code=st)
            return idempotent(request, fid, body.model_dump(), lambda: eng.create_proposal(fid, body.model_dump()), required=False)

    @app.post("/v1/proposals/{proposal_id}/submit")
    def submit(request: Request, proposal_id: str):
        fid = fid_of(request)
        with eng.lock:
            return idempotent(request, fid, {"proposal_id": proposal_id}, lambda: eng.submit(fid, proposal_id), required=True)

    @app.get("/v1/proposals")
    def list_proposals(request: Request, status: str | None = None):
        fid = fid_of(request)
        with eng.lock:
            rows = [p for p in eng.state["proposals"].values() if p["freelancer_id"] == fid and (not status or p["status"] == status)]
            return {"proposals": [eng.public_proposal(p) for p in rows]}

    @app.get("/v1/proposals/{proposal_id}")
    def get_proposal(request: Request, proposal_id: str):
        fid = fid_of(request)
        with eng.lock:
            return eng.public_proposal(eng.get_proposal(fid, proposal_id))

    @app.get("/v1/threads")
    def threads(request: Request):
        fid = fid_of(request)
        with eng.lock:
            rows = [eng.public_thread(t) for t in eng.state["threads"].values() if t["freelancer_id"] == fid]
            return {"threads": sorted(rows, key=lambda t: t["last_message_at"], reverse=True)}

    @app.get("/v1/messages")
    def messages(request: Request, thread_id: str):
        fid = fid_of(request)
        with eng.lock:
            t = eng.thread_for(fid, thread_id)
            t["unread"] = 0
            return {"thread_id": thread_id,
                    "messages": [eng.public_message(m) for m in eng.state["messages"] if m["thread_id"] == thread_id]}

    @app.post("/v1/messages")
    def post_message(request: Request, body: MessageIn):
        fid = fid_of(request)
        with eng.lock:
            return idempotent(request, fid, body.model_dump(), lambda: eng.post_message(fid, body.thread_id, body.body), required=True)

    @app.get("/v1/events")
    def events(request: Request, since: int = 0):
        fid = fid_of(request)
        with eng.lock:
            return [{k: v for k, v in e.items() if k != "freelancer_id"} for e in eng.state["events"]
                    if e["freelancer_id"] == fid and e["event_id"] > since]

    # ---- simulation control ------------------------------------------------------------------
    @app.post("/v1/sim/tick")
    def tick(body: TickIn | None = None):
        with eng.lock:
            return eng.tick((body or TickIn()).steps)

    @app.post("/v1/sim/reset")
    def reset(body: ResetIn | None = None):
        with eng.lock:
            hits.clear()
            return eng.reset(body.seed if body else None)

    @app.get("/v1/sim/clock")
    def sim_clock():
        return {"now": iso_ts(eng.state["clock"]), "seed": eng.state["seed"]}

    return app


app = create_app()
