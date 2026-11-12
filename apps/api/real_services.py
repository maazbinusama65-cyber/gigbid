"""RealServices: the web API driven by the real LangGraph graphs, MCP tools, memory and traces.

* Long agent runs execute as background tasks (or in the Arq worker when GIGBID_USE_WORKER=1), never inside
  the request; progress is read from the append-only per-run trace file, so the SSE stream works the same
  for both and replays history after a page refresh.
* Pending approvals live in two places on purpose: the LangGraph checkpoint (durable interrupt) and the
  `approvals` table (so the UI can list them). Neither is lost on a refresh or an API restart.
* Every method filters by ``user.id`` (tenant isolation); other tenants' ids raise NotFound.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent.config_loader import ROOT, Config, load_config
from agent.handoffs import ApprovalDecision, ApprovalRequest
from agent.llm import LLM
from types import SimpleNamespace

from agent.guardrails import detect_injection
from agent.nodes.liaison import classify_heuristic
from agent.nodes.scout import unwrap
from agent.policy import Policy
from agent.runtime import GraphRuntime, make_checkpointer
from agent.tools import ToolGateway, ToolUnavailable, default_memory_servers
from agent.trace import TraceRecorder, new_trace_id
from apps.api.auth.deps import CurrentUser
from apps.api.errors import NotFound
from apps.api.logging_setup import current_trace_id
from apps.api.real_store import RealStore
from apps.api.schemas.analytics import (
    AnalyticsSummary,
    CategoryStat,
    ConnectsPoint,
    CostLatency,
    RejectionReason,
)
from apps.api.schemas.approvals import ApprovalItem, ApprovalList, DecisionResult
from apps.api.schemas.common import MarketplaceStatus
from apps.api.schemas.jobs import (
    AnalyzeResponse,
    ClientSummary,
    JobBudget,
    JobDetail,
    JobListResponse,
    JobPosting,
    JobSummary,
    SkipResponse,
)
from apps.api.schemas.messages import (
    ChatMessage,
    InterviewSlot,
    MessageDecisionRequest,
    MessageDecisionResult,
    SuggestedReply,
    ThreadDetail,
    ThreadList,
    ThreadSummary,
)
from apps.api.schemas.pipeline import STAGES, MarketplaceEvent, PipelineBoard, PipelineCard, PipelineColumn
from apps.api.schemas.proposals import ProposalStudio, RegenerateRequest
from apps.api.schemas.runs import RunDetail, RunList, RunStep, RunSummary, TraceResponse, TraceSpan
from apps.api.schemas.settings import (
    MemoryItem,
    MemoryList,
    OnboardingRequest,
    OnboardingState,
    PersonaOption,
    PortfolioFile,
    SavedSearch,
    UserSettings,
    UserSettingsUpdate,
)

log = logging.getLogger("gigbid.real_services")
_POLICY_CTX = SimpleNamespace(policy=Policy())
PERSONAS = ("ai_ml", "fullstack", "data_analyst")
TERMINAL = {"done", "run_error"}
STATUS_MAP = {"awaiting_approval": "awaiting_approval", "submitted": "submitted", "skipped": "skipped",
              "rejected": "rejected", "blocked": "blocked", "needs_attention": "needs_attention",
              "dead_letter": "dead_letter", "running": "running"}


def _iso(ts: float | None) -> str:
    return datetime.fromtimestamp(ts or time.time(), UTC).isoformat()


def _profile(persona: str) -> dict:
    p = ROOT / "data" / "personas" / persona / "profile.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


class RealServices:
    def __init__(self, cfg: Config | None = None, store: RealStore | None = None,
                 servers: dict | None = None, llm: LLM | None = None, transport: str | None = None):
        self.cfg = cfg or load_config()
        self.store = store or RealStore(os.getenv("REAL_STORE_DB", ROOT / "data" / "processed" / "real_store.sqlite"))
        self._servers = servers
        self._llm = llm
        self._transport = transport
        self._rts: dict[str, GraphRuntime] = {}
        self._gateways: dict[str, ToolGateway] = {}
        self._checkpointer = None
        self._memory = None
        self._boot_lock = asyncio.Lock()
        self.tasks: dict[str, asyncio.Task] = {}
        self.use_worker = os.getenv("GIGBID_USE_WORKER") == "1"

    # ------------------------------------------------------------------ plumbing
    async def _boot(self) -> None:
        async with self._boot_lock:
            if self._checkpointer is None:
                self._checkpointer = await make_checkpointer()
                from agent.memory.store import LongTermMemory, make_store

                self._memory = LongTermMemory(make_store(os.getenv("MEMORY_DB")), self.cfg)
                if self._servers is None and (self._transport or self.cfg["tool_servers"]["transport"]) == "memory":
                    self._servers = default_memory_servers()
                self._llm = self._llm or LLM(self.cfg)

    def persona(self, user: CurrentUser) -> str:
        return user.persona_id if user.persona_id in PERSONAS else "ai_ml"

    def gateway(self, user: CurrentUser) -> ToolGateway:
        pid = self.persona(user)
        if pid not in self._gateways:
            self._gateways[pid] = ToolGateway(self.cfg, user_id=pid, servers=self._servers, transport=self._transport)
        return self._gateways[pid]

    async def rt(self, user: CurrentUser) -> GraphRuntime:
        await self._boot()
        pid = self.persona(user)
        if pid not in self._rts:
            self._rts[pid] = GraphRuntime(self.cfg, self.gateway(user), llm=self._llm, memory=self._memory,
                                          checkpointer=self._checkpointer, policy=Policy())
        return self._rts[pid]

    async def _call(self, user: CurrentUser, agent: str, tool: str, args: dict | None = None) -> Any:
        await self._boot()
        return await self.gateway(user).call(agent, tool, args or {}, trace_id=current_trace_id())

    def _portfolio_ids(self, user: CurrentUser) -> list[str]:
        ids = [self.persona(user)]
        if (ROOT / "data" / "processed" / "index" / f"u-{user.id}").exists():
            ids.append(f"u-{user.id}")
        return ids

    # ------------------------------------------------------------------ settings
    def _default_settings(self, user: CurrentUser) -> UserSettings:
        prof = _profile(self.persona(user))
        searches = [SavedSearch(search_id=f"ss{i}", name=s.get("name", f"Search {i + 1}"), query=s.get("query", ""),
                                category=s.get("category"), interval_minutes=60)
                    for i, s in enumerate(prof.get("saved_searches", []))]
        return UserSettings(weekly_connects_budget=int(prof.get("weekly_connects_budget", 60)),
                            min_budget_usd=int(prof.get("min_project_budget_usd", 300)),
                            hourly_rate_usd=int(prof.get("hourly_rate_usd", 65)),
                            min_fit_score=float(self.cfg["thresholds"]["minimum_fit_score"]), saved_searches=searches)

    async def get_settings(self, user: CurrentUser) -> UserSettings:
        stored = self.store.get_settings(user.id)
        return UserSettings(**stored) if stored else self._default_settings(user)

    async def update_settings(self, user: CurrentUser, update: UserSettingsUpdate) -> UserSettings:
        cur = await self.get_settings(user)
        new = cur.model_copy(update=update.model_dump(exclude_unset=True, exclude_none=True))
        self.store.put_settings(user.id, new.model_dump())
        return new

    async def _graph_settings(self, user: CurrentUser) -> dict:
        s = await self.get_settings(user)
        return {"min_project_budget_usd": s.min_budget_usd, "hourly_rate_usd": s.hourly_rate_usd,
                "weekly_connects_budget": s.weekly_connects_budget, "min_fit_score": s.min_fit_score,
                "portfolio_ids": self._portfolio_ids(user),
                "autonomy": {"auto_skip_low_fit": s.autonomy_level == "scout", "auto_send": False}}

    # ------------------------------------------------------------------ jobs
    def _budget(self, b: dict | None) -> JobBudget:
        b = b or {}
        return JobBudget(type=b.get("type", "fixed"), min=b.get("min"), max=b.get("max"), currency=b.get("currency", "USD"))

    def _summary(self, job: dict, st: dict | None) -> JobSummary:
        s = (st or {}).get("summary", {})
        return JobSummary(
            job_id=job["job_id"], title=job["title"], category=job.get("category", ""), budget=self._budget(job.get("budget")),
            posted_at=job.get("posted_at", ""), fit_score=s.get("fit"), risk_score=s.get("risk"), risk_flags=s.get("flags", []),
            is_scam=bool(s.get("is_scam")), injection_detected=bool(s.get("injection")), recommendation=s.get("recommendation"),
            suggested_price=s.get("price"), connects_cost=int(job.get("connects_cost", 0)),
            status=(st or {}).get("status", "new"), top_skills=list(job.get("required_skills", []))[:4],
            run_id=(st or {}).get("run_id"))

    async def list_jobs(self, user: CurrentUser, *, q: str | None = None, category: str | None = None,
                        min_fit: float | None = None, include_skipped: bool = False, sort: str = "fit") -> JobListResponse:
        degraded = False
        found: dict[str, dict] = {}
        try:
            res = await self._call(user, "scout", "search_jobs", {"query": q, "category": category, "limit": 50})
            found = {j["job_id"]: j for j in (res.get("jobs", res) if isinstance(res, dict) else res)}
        except ToolUnavailable:
            degraded = True
        states = {r["job_id"]: r for r in self.store.list_jobs(user.id)}
        rows: list[JobSummary] = []
        for jid, job in found.items():
            rows.append(self._summary(job, states.get(jid)))
        for jid, st in states.items():          # analysed jobs stay visible even if the feed moved on / is down
            if jid not in found and not q and not category:
                job = {"job_id": jid, "title": st["title"], "category": st["category"], "posted_at": ""}
                rows.append(self._summary(job, st))
        if not include_skipped:
            rows = [r for r in rows if r.status != "skipped"]
        if min_fit is not None:
            rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
        key = {"fit": lambda r: -(r.fit_score if r.fit_score is not None else -1), "newest": lambda r: r.posted_at,
               "risk": lambda r: r.risk_score or 0}.get(sort, lambda r: -(r.fit_score or -1))
        rows.sort(key=key, reverse=(sort == "newest"))
        return JobListResponse(jobs=rows, total=len(rows), marketplace_degraded=degraded,
                               categories=sorted({r.category for r in rows if r.category}))

    async def get_job_detail(self, user: CurrentUser, job_id: str) -> JobDetail:
        try:
            job = unwrap(await self._call(user, "scout", "get_job", {"job_id": job_id}), "job")
        except ToolUnavailable:
            st = self.store.get_job(user.id, job_id)
            if not st:
                raise
            job = {"job_id": job_id, "client_id": "", "title": st["title"], "description": "(marketplace unavailable)",
                   "category": st["category"], "posted_at": ""}
        client = None
        if job.get("client_id"):
            try:
                c = unwrap(await self._call(user, "risk_assessor", "get_client_history", {"client_id": job["client_id"]}), "client")
                client = ClientSummary(**{k: c.get(k) for k in ClientSummary.model_fields if c.get(k) is not None}) if c else None
            except Exception:  # noqa: BLE001 - client card is optional
                client = None
        rt = await self.rt(user)
        snap = await rt.state(f"bid:{user.id}:{job_id}")
        v = (snap or {}).get("values", {})
        st = self.store.get_job(user.id, job_id)
        notes = []
        if v.get("risk_report", {}).get("injection_detected"):
            notes.append("An instruction embedded in this post was detected and ignored (treated as data).")
        ev_ids = set(v.get("fit_report", {}).get("evidence_ids", []))
        posting = JobPosting(
            job_id=job["job_id"], client_id=job.get("client_id", ""), title=job.get("title", ""),
            description=job.get("description", ""), category=job.get("category", ""),
            required_skills=list(job.get("required_skills", [])), budget=self._budget(job.get("budget")),
            duration_days=job.get("duration_days"), screening_questions=list(job.get("screening_questions", [])),
            posted_at=job.get("posted_at", ""), connects_cost=int(job.get("connects_cost", 0)))
        return JobDetail(
            job=posting,
            client=client, spec=v.get("job_spec") or None, risk=v.get("risk_report") or None, fit=v.get("fit_report") or None,
            evidence=[e for e in v.get("evidence", []) if e["id"] in ev_ids] or v.get("evidence", [])[:8],
            price=v.get("price_quote") or None, decision=v.get("decision") or None,
            status=(st or {}).get("status", "new"), sanitized_notes=notes,
            latest_run_id=(st or {}).get("run_id"), approval_id=self._pending_id(user, f"bid:{user.id}:{job_id}"))

    def _pending_id(self, user: CurrentUser, thread_id: str) -> str | None:
        a = self.store.get_approval(user.id, thread_id)
        return a["approval_id"] if a and a["status"] == "pending" else None

    async def analyze_job(self, user: CurrentUser, job_id: str) -> AnalyzeResponse:
        run_id = f"bid:{user.id}:{job_id}"
        existing = self.store.get_run(user.id, run_id)
        if existing and existing["status"] in ("running", "awaiting_approval", "submitted"):
            return AnalyzeResponse(run_id=run_id, job_id=job_id, status="running")
        trace_id = current_trace_id() or new_trace_id()
        title = (self.store.get_job(user.id, job_id) or {}).get("title", job_id)
        self.store.upsert_run(run_id, user.id, kind="bid", job_id=job_id, title=title, status="running",
                              started_at=time.time(), trace_id=trace_id, thread_id=run_id)
        self.store.set_job(user.id, job_id, "analyzing", run_id, title, "", {})
        if self.use_worker:
            await self._enqueue(user, job_id)
        else:
            self.tasks[run_id] = asyncio.create_task(self._bid_task(user, job_id, run_id, trace_id))
        return AnalyzeResponse(run_id=run_id, job_id=job_id, status="queued")

    async def _enqueue(self, user: CurrentUser, job_id: str) -> None:
        from arq import create_pool
        from arq.connections import RedisSettings

        pool = await create_pool(RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0")))
        await pool.enqueue_job("analyse_job", user.id, job_id, _job_id=f"bid:{user.id}:{job_id}")

    async def _bid_task(self, user: CurrentUser, job_id: str, run_id: str, trace_id: str) -> None:
        rt = await self.rt(user)
        last: dict = {}
        try:
            async for ev in rt.run_bid(user.id, self.persona(user), job_id, await self._graph_settings(user),
                                       thread_id=run_id, trace_id=trace_id):
                last = ev
        except Exception as e:  # noqa: BLE001
            log.exception("bid run failed")
            last = {"type": "error", "data": {"error": str(e)}}
        await self.finish_bid(user, job_id, run_id, last)

    async def finish_bid(self, user: CurrentUser, job_id: str, run_id: str, last: dict) -> None:
        record_bid_result(self.store, user.id, job_id, run_id, last)

    # ------------------------------------------------------------------ approvals
    def _item(self, a: dict) -> ApprovalItem:
        return ApprovalItem(approval_id=a["approval_id"], status=a["status"], created_at=_iso(a["created_at"]),
                            decided_at=_iso(a["decided_at"]) if a.get("decided_at") else None, run_id=a.get("run_id"),
                            title=a.get("title", ""), request=ApprovalRequest(**a["request"]),
                            decision=ApprovalDecision(**a["decision"]) if a.get("decision") else None)

    async def list_approvals(self, user: CurrentUser, status: str | None = None) -> ApprovalList:
        rows = self.store.list_approvals(user.id, status)
        return ApprovalList(approvals=[self._item(r) for r in rows],
                            pending_count=sum(1 for r in self.store.list_approvals(user.id, "pending")))

    async def decide_approval(self, user: CurrentUser, approval_id: str, decision: ApprovalDecision) -> DecisionResult:
        a = self.store.get_approval(user.id, approval_id)
        if not a or a["kind"] == "message":
            raise NotFound("approval not found")
        if a["status"] != "pending":
            return DecisionResult(approval_id=approval_id, status=a["status"], run_id=a["run_id"], message="already decided")
        rt = await self.rt(user)
        last: dict = {}
        async for ev in rt.resume(a["thread_id"], decision.model_dump(), kind="bid"):
            last = ev
        state = last.get("state", {}) or {}
        status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[decision.action]
        job_id = state.get("job_id") or a["thread_id"].split(":")[-1]
        if last.get("interrupted") and last.get("pending"):          # compliance changed the edit: review again
            self.store.put_approval(approval_id, user.id, a["run_id"], a["thread_id"], last["pending"].get("kind", "proposal"),
                                    a["title"], last["pending"])
            return DecisionResult(approval_id=approval_id, status="edited", run_id=a["run_id"],
                                  message="Compliance changed your edit; please review the cleaned text.")
        self.store.decide_approval(approval_id, status, decision.model_dump())
        sub = state.get("submission") or {}
        reason = state.get("status_reason") or ""
        queued = "marketplace_unavailable" in reason
        if decision.action == "reject":
            self.store.add_rejection(user.id, (decision.reason or "no reason given")[:120])
        self.store.upsert_run(a["run_id"], user.id, status=STATUS_MAP.get(state.get("status", ""), "running"),
                              finished_at=time.time())
        if state.get("status") == "submitted" and sub.get("proposal_id"):
            job = state.get("job", {})
            self.store.put_proposal(user.id, sub["proposal_id"], job_id=job_id, title=job.get("title", job_id),
                                    category=job.get("category", ""), stage="submitted",
                                    bid_amount=state.get("price_quote", {}).get("amount"),
                                    connects_spent=int(sub.get("connects_spent") or 0), last_event="submitted",
                                    client_name=job.get("client_id", ""))
        return DecisionResult(approval_id=approval_id, status=status, run_id=a["run_id"],
                              submitted=state.get("status") == "submitted", queued=queued,
                              proposal_id=sub.get("proposal_id"), connects_spent=int(sub.get("connects_spent") or 0),
                              message=reason if queued else "")

    # ------------------------------------------------------------------ proposal studio
    async def get_proposal_studio(self, user: CurrentUser, job_id: str) -> ProposalStudio:
        rt = await self.rt(user)
        thread = f"bid:{user.id}:{job_id}"
        snap = await rt.state(thread)
        if not snap or not snap["values"].get("proposal_draft"):
            raise NotFound("no draft for this job yet; analyse it first")
        v = snap["values"]
        draft = v["proposal_draft"]
        ev_ids = set(draft.get("evidence_ids", []))
        crit = (v.get("critiques") or [None])[-1]
        a = self.store.get_approval(user.id, thread)
        return ProposalStudio(
            job_id=job_id, job_title=v.get("job", {}).get("title", job_id), draft=draft,
            paragraphs=[p for p in re.split(r"\n\s*\n", draft["cover_letter"]) if p.strip()] or [draft["cover_letter"]],
            screening_questions=v.get("job", {}).get("screening_questions", []),
            evidence=[e for e in v.get("evidence", []) if e["id"] in ev_ids], critic=crit,
            compliance=v.get("compliance_verdict") or None, risk=v.get("risk_report") or None,
            price=v.get("price_quote") or None, dry_run=v.get("dry_run") or None,
            approval_id=a["approval_id"] if a else None, approval_status=a["status"] if a else None)

    async def regenerate_paragraph(self, user: CurrentUser, job_id: str, req: RegenerateRequest) -> ProposalStudio:
        studio = await self.get_proposal_studio(user, job_id)
        paras = list(studio.paragraphs)
        if req.paragraph_index >= len(paras):
            raise NotFound("paragraph index out of range")
        rt = await self.rt(user)
        new = paras[req.paragraph_index]
        if rt.llm.available:
            from agent.guardrails import wrap_untrusted
            from agent.prompts import load_prompt

            _, system = load_prompt("writer")
            ev = "\n".join(f"[{e.id}] {e.text[:400]}" for e in studio.evidence)
            res = await rt.llm.chat("writer", system + "\nRewrite ONLY the paragraph below; return the paragraph text only.",
                                    f"EVIDENCE:\n{ev}\n\nINSTRUCTION: {req.instruction or 'make it more specific'}\n\n"
                                    f"PARAGRAPH:\n{wrap_untrusted(paras[req.paragraph_index], 'draft')}", max_tokens=400)
            new = res.text or new
        else:                               # offline: re-pick the best evidence sentence for this paragraph
            from agent.nodes.common import best_sentence

            cited = re.findall(r"\[([^\]\s]+)\]", paras[req.paragraph_index])
            byid = {e.id: e for e in studio.evidence}
            for cid in cited:
                if cid in byid:
                    alt = best_sentence(byid[cid].text, req.instruction, 240)
                    if alt:
                        new = re.sub(r":.*\[", f": {alt} [", paras[req.paragraph_index], count=1)
        paras[req.paragraph_index] = new
        thread = f"bid:{user.id}:{job_id}"
        ctx = rt.ctx_for(thread)
        graph = rt.bid_graph(ctx)
        draft = {**studio.draft.model_dump(), "cover_letter": "\n\n".join(paras)}
        await graph.aupdate_state({"configurable": {"thread_id": thread}}, {"proposal_draft": draft}, as_node="dry_run")
        a = self.store.get_approval(user.id, thread)
        if a:
            a["request"]["draft"] = draft
            self.store.put_approval(thread, user.id, a["run_id"], thread, a["kind"], a["title"], a["request"])
        return await self.get_proposal_studio(user, job_id)

    async def skip_job(self, user: CurrentUser, job_id: str, reason: str) -> SkipResponse:
        st = self.store.get_job(user.id, job_id)
        self.store.set_job(user.id, job_id, "skipped", (st or {}).get("run_id"), (st or {}).get("title", job_id),
                           (st or {}).get("category", ""), {**(st or {}).get("summary", {}), "reason": reason})
        if reason:
            self.store.add_rejection(user.id, f"skipped: {reason}"[:120])
        return SkipResponse(job_id=job_id)

    # ------------------------------------------------------------------ pipeline / events
    async def _sync_events(self, user: CurrentUser) -> tuple[list[dict], bool]:
        try:
            res = await self._call(user, "client_liaison", "list_events", {"since": self.store.get_cursor(user.id)})
        except ToolUnavailable:
            return [], True
        events = res.get("events", [])
        stage_of = {"viewed": "viewed", "replied": "replied", "interview": "interview", "hired": "hired", "lost": "lost"}
        mine = {p["proposal_id"]: p for p in self.store.list_proposals(user.id)}
        for e in events:
            p = mine.get(e.get("proposal_id"))
            if p and e["type"] in stage_of:
                self.store.put_proposal(user.id, p["proposal_id"], stage=stage_of[e["type"]], last_event=e["type"],
                                        thread_id=e.get("thread_id") or p.get("thread_id"), updated_at=time.time())
        if res.get("last_event_id") is not None:
            self.store.set_cursor(user.id, str(res["last_event_id"]))
        return events, False

    async def pipeline_board(self, user: CurrentUser) -> PipelineBoard:
        events, degraded = await self._sync_events(user)
        cols = {s: PipelineColumn(stage=s, label=s.capitalize()) for s in STAGES}
        for p in self.store.list_proposals(user.id):
            cols[p["stage"]].cards.append(PipelineCard(
                proposal_id=p["proposal_id"], job_id=p["job_id"], title=p["title"], client_name=p.get("client_name") or "",
                stage=p["stage"], bid_amount=p.get("bid_amount"), connects_spent=int(p.get("connects_spent") or 0),
                updated_at=_iso(p["updated_at"]), last_event=p.get("last_event") or "", thread_id=p.get("thread_id")))
        for a in self.store.list_approvals(user.id, "pending"):      # drafted = waiting for the user's approval
            if a["kind"] != "message":
                req = a["request"]
                cols["drafted"].cards.append(PipelineCard(
                    proposal_id=a["approval_id"], job_id=req.get("job_id") or "", title=a["title"], stage="drafted",
                    bid_amount=(req.get("price") or {}).get("amount"), updated_at=_iso(a["created_at"]), last_event="awaiting approval"))
        recent = [MarketplaceEvent(event_id=str(e["event_id"]), ts=e.get("ts") or "", type=e["type"],
                                   proposal_id=e.get("proposal_id"), thread_id=e.get("thread_id"),
                                   summary=f"{e['type']} on {e.get('proposal_id') or e.get('thread_id')}")
                  for e in events[-10:]]
        return PipelineBoard(columns=list(cols.values()), recent_events=recent, marketplace_degraded=degraded,
                             updated_at=datetime.now(UTC).isoformat())

    # ------------------------------------------------------------------ messages
    async def _threads(self, user: CurrentUser) -> tuple[list[dict], bool]:
        try:
            res = await self._call(user, "client_liaison", "list_messages", {})
        except ToolUnavailable:
            return [], True
        return res.get("threads", []), False

    async def list_threads(self, user: CurrentUser) -> ThreadList:
        threads, degraded = await self._threads(user)
        out: list[ThreadSummary] = []
        for t in threads:
            tid = t.get("thread_id")
            try:
                msgs = (await self._call(user, "client_liaison", "list_messages", {"thread_id": tid})).get("messages", [])
            except ToolUnavailable:
                msgs, degraded = [], True
            last = msgs[-1] if msgs else {}
            client_last = last.get("sender") in ("client", "them")
            intent = classify_heuristic(last.get("body", ""), _POLICY_CTX).intent if client_last else "other"
            a = self.store.get_approval(user.id, f"conv:{user.id}:{tid}")
            out.append(ThreadSummary(
                thread_id=tid, client_name=t.get("client_name") or t.get("client_id") or "client",
                job_title=t.get("job_title") or t.get("job_id") or "", last_message=(last.get("body") or "")[:160],
                last_message_at=last.get("ts") or t.get("last_message_at") or "", unread=bool(t.get("unread")),
                intent=intent, status="needs_reply" if client_last else "awaiting_client",
                has_suggested_reply=bool(a and a["status"] == "pending"),
                injection_detected=bool(detect_injection(last.get("body", "")))))
        return ThreadList(threads=out, marketplace_degraded=degraded)

    async def get_thread(self, user: CurrentUser, thread_id: str) -> ThreadDetail:
        res = await self._call(user, "client_liaison", "list_messages", {"thread_id": thread_id})
        msgs = res.get("messages", [])
        if not msgs and not any(t.get("thread_id") == thread_id for t in (await self._threads(user))[0]):
            raise NotFound("thread not found")
        cid = f"conv:{user.id}:{thread_id}"
        a = self.store.get_approval(user.id, cid)
        client_last = bool(msgs) and msgs[-1].get("sender") in ("client", "them")
        if client_last and (not a or a["status"] != "pending") and not (a and a.get("request", {}).get("draft", {}).get("client_message") == msgs[-1].get("body") and a["status"] != "pending"):
            rt = await self.rt(user)
            last: dict = {}
            tinfo = next((t for t in (await self._threads(user))[0] if t.get("thread_id") == thread_id), {})
            async for ev in rt.run_conversation(user.id, self.persona(user), thread_id, tinfo.get("job_id"), await self._graph_settings(user)):
                last = ev
            if last.get("interrupted") and last.get("pending"):
                self.store.put_approval(cid, user.id, cid, cid, "message", "Reply", last["pending"])
                a = self.store.get_approval(user.id, cid)
        summ = (await self.list_threads(user))
        summary = next((t for t in summ.threads if t.thread_id == thread_id), None)
        sug, slots = None, []
        if a and a["status"] == "pending":
            d = a["request"]["draft"]
            slots = [InterviewSlot(slot_id=str(i), start=s.get("start", ""), end=s.get("end", ""), label=s.get("start", ""))
                     for i, s in enumerate(d.get("slots", []))]
            sug = SuggestedReply(approval_id=cid, text=d.get("text", ""), intent=d.get("intent", "other"),
                                 rationale="Drafted from your portfolio evidence and calendar; nothing is sent until you approve.")
        flagged = [bool(detect_injection(m.get("body", ""))) for m in msgs]
        return ThreadDetail(
            thread=summary or ThreadSummary(thread_id=thread_id, client_name="client", job_title="", last_message="", last_message_at=""),
            messages=[ChatMessage(message_id=str(m.get("message_id", i)), sender="client" if m.get("sender") in ("client", "them") else "freelancer",
                                  body=m.get("body", ""), ts=m.get("ts", ""), flagged=flagged[i]) for i, m in enumerate(msgs)],
            suggested_reply=sug, slots=slots, safety_note="A client message contained an instruction aimed at an AI; it was treated as data." if any(flagged) else "")

    async def decide_message(self, user: CurrentUser, thread_id: str, req: MessageDecisionRequest) -> MessageDecisionResult:
        cid = f"conv:{user.id}:{thread_id}"
        a = self.store.get_approval(user.id, cid)
        if not a or a["status"] != "pending":
            raise NotFound("no pending reply for this thread")
        rt = await self.rt(user)
        if req.slot_id is not None and req.slot_id.isdigit():
            slots = list(a["request"]["draft"].get("slots", []))
            i = int(req.slot_id)
            if i < len(slots):
                slots.insert(0, slots.pop(i))
                graph = rt.conv_graph(rt.ctx_for(cid))
                await graph.aupdate_state({"configurable": {"thread_id": cid}}, {"slots": slots}, as_node="draft_reply")
        dec = ApprovalDecision(action=req.action, edited_text=req.edited_text, reason=req.reason)
        last: dict = {}
        async for ev in rt.resume(cid, dec.model_dump(), kind="conversation"):
            last = ev
        state = last.get("state", {}) or {}
        self.store.decide_approval(cid, {"approve": "approved", "edit": "edited", "reject": "rejected"}[req.action], dec.model_dump())
        if req.action == "reject":
            return MessageDecisionResult(thread_id=thread_id, status="rejected")
        queued = "marketplace_unavailable" in (state.get("status_reason") or "")
        hold = (state.get("sent") or {}).get("hold")
        slot = None
        if hold and isinstance(hold, dict):
            slot = InterviewSlot(slot_id="0", start=str(hold.get("start", "")), end=str(hold.get("end", "")), label=str(hold.get("start", "")))
        return MessageDecisionResult(thread_id=thread_id, status="queued" if queued else "sent", interview_hold=slot)

    # ------------------------------------------------------------------ runs / trace
    def _summary_run(self, r: dict) -> RunSummary:
        return RunSummary(run_id=r["run_id"], kind=r.get("kind") or "bid", job_id=r.get("job_id"), title=r.get("title") or "",
                          status=r.get("status") or "running", started_at=_iso(r.get("started_at")),
                          finished_at=_iso(r["finished_at"]) if r.get("finished_at") else None,
                          total_tokens=int(r.get("total_tokens") or 0), cost_usd=float(r.get("cost_usd") or 0),
                          latency_ms=int(r.get("latency_ms") or 0), trace_id=r.get("trace_id") or "")

    def _owned(self, user: CurrentUser, run_id: str) -> dict:
        r = self.store.get_run(user.id, run_id)
        if not r:
            raise NotFound("run not found")
        return r

    async def list_runs(self, user: CurrentUser) -> RunList:
        return RunList(runs=[self._summary_run(r) for r in self.store.list_runs(user.id)])

    async def get_run(self, user: CurrentUser, run_id: str) -> RunDetail:
        r = self._owned(user, run_id)
        events = TraceRecorder(run_id).read()
        steps: list[RunStep] = []
        open_: dict[str, RunStep] = {}
        prev_tokens = 0
        for e in events:
            if e["type"] == "node_start":
                s = RunStep(node=e["node"], label=e["node"].replace("_", " "), status="running", started_at=_iso(e["ts"]))
                steps.append(s)
                open_[e["node"]] = s
            elif e["type"] == "node_end" and e["node"] in open_:
                s = open_.pop(e["node"])
                d = e["data"]
                s.status, s.duration_ms = "done", int(float(d.get("latency_s", 0)) * 1000)
                tok = int(d.get("tokens", 0) or 0)
                s.tokens_in, prev_tokens = max(0, tok - prev_tokens), tok
                s.summary = f"status={d.get('status')}" if d.get("status") else ""
            elif e["type"] == "interrupt" and "approval" in open_:
                open_["approval"].status = "interrupted"
            elif e["type"] == "node_error" and e["node"] in open_:
                open_[e["node"]].status = "failed"
                open_[e["node"]].summary = str(e["data"].get("error", ""))[:120]
        a = self.store.get_approval(user.id, run_id)
        notes = [e["data"].get("reason") for e in events if e["type"] == "done" and e["data"].get("reason")]
        return RunDetail(summary=self._summary_run(r), steps=steps,
                         trace_url=self.cfg_trace_url(r.get("trace_id") or run_id),
                         approval_id=a["approval_id"] if a and a["status"] == "pending" else None, notes=notes)

    def cfg_trace_url(self, trace_id: str) -> str:
        return os.getenv("TRACE_URL_TEMPLATE", "/runs/{trace_id}").format(trace_id=trace_id)

    async def get_trace(self, user: CurrentUser, run_id: str) -> TraceResponse:
        r = self._owned(user, run_id)
        events = TraceRecorder(run_id).read()
        t0 = events[0]["ts"] if events else time.time()
        spans: list[TraceSpan] = []
        for i, e in enumerate(events):
            if e["type"] == "node_end":
                d = e["data"]
                spans.append(TraceSpan(span_id=f"n{i}", name=e["node"], kind="node", start_ms=int((e["ts"] - t0) * 1000) - int(float(d.get("latency_s", 0)) * 1000),
                                       duration_ms=int(float(d.get("latency_s", 0)) * 1000), attributes={k: v for k, v in d.items() if k != "keys"}))
            elif e["type"] == "tool":
                d = e["data"]
                spans.append(TraceSpan(span_id=f"t{i}", parent_id=None, name=d.get("tool", "tool"), kind="mcp",
                                       start_ms=int((e["ts"] - t0) * 1000), duration_ms=int(float(d.get("latency_s", 0)) * 1000),
                                       attributes={"agent": e["node"], "ok": d.get("ok"), "args": d.get("args"), "result": d.get("result")}))
        return TraceResponse(trace_id=r.get("trace_id") or run_id, run_id=run_id, url=self.cfg_trace_url(r.get("trace_id") or run_id),
                             spans=spans, total_cost_usd=float(r.get("cost_usd") or 0),
                             total_ms=int(((events[-1]["ts"] - t0) if events else 0) * 1000))

    async def stream_run(self, user: CurrentUser, run_id: str) -> AsyncIterator[dict]:
        self._owned(user, run_id)
        rec = TraceRecorder(run_id)
        offset, deadline = 0, time.monotonic() + 600
        kinds = {"node_start": "node_start", "node_end": "node_end", "interrupt": "interrupt", "degraded": "degraded",
                 "node_error": "error", "run_error": "error", "done": "done"}
        while time.monotonic() < deadline:
            events = rec.read()
            for e in events[offset:]:
                if e["type"] in kinds:
                    yield {"type": kinds[e["type"]], "node": e.get("node"), "ts": _iso(e["ts"]), "data": e.get("data", {})}
                elif e["type"] == "tool":
                    d = e["data"]
                    yield {"type": "token", "node": e.get("node"), "ts": _iso(e["ts"]),
                           "data": {"tool": d.get("tool"), "ok": d.get("ok"), "latency_s": d.get("latency_s")}}
            offset = len(events)
            run = self.store.get_run(user.id, run_id) or {}
            if any(e["type"] in TERMINAL for e in events) and run.get("status") != "running":
                return
            await asyncio.sleep(0.25)

    # ------------------------------------------------------------------ analytics / memory
    async def analytics_summary(self, user: CurrentUser) -> AnalyticsSummary:
        await self._sync_events(user)
        props = self.store.list_proposals(user.id)
        runs = [r for r in self.store.list_runs(user.id, 1000) if r.get("finished_at")]
        by: dict[str, dict] = {}
        for p in props:
            c = by.setdefault(p["category"] or "other", {"sent": 0, "rep": 0, "hire": 0})
            c["sent"] += 1
            c["rep"] += int(p["stage"] in ("replied", "interview", "hired"))
            c["hire"] += int(p["stage"] == "hired")
        cats = [CategoryStat(category=k, proposals_sent=v["sent"], replies=v["rep"], hires=v["hire"],
                             reply_rate=round(v["rep"] / v["sent"], 3), hire_rate=round(v["hire"] / v["sent"], 3)) for k, v in by.items()]
        lat = sorted(r["latency_ms"] / 1000 for r in runs) or [0.0]
        pct = lambda q: lat[min(len(lat) - 1, int(q * (len(lat) - 1) + 0.5))]  # noqa: E731
        cost = [r["cost_usd"] for r in runs] or [0.0]
        drafted = [r for r in runs if r["status"] in ("awaiting_approval", "submitted")]
        pts = [ConnectsPoint(period="all time", connects_spent=sum(int(p["connects_spent"] or 0) for p in props),
                             replies=sum(v["rep"] for v in by.values()), hires=sum(v["hire"] for v in by.values()))] if props else []
        return AnalyticsSummary(
            is_sample=False, period_label="all time",
            totals={"proposals_sent": len(props), "jobs_analysed": len(runs), "pending_approvals": len(self.store.list_approvals(user.id, "pending"))},
            by_category=cats, connects_vs_outcomes=pts,
            cost_latency=CostLatency(proposals_measured=len(drafted), avg_cost_usd_per_proposal=round(sum(r["cost_usd"] for r in drafted) / max(1, len(drafted)), 6),
                                     p50_latency_s=round(pct(0.5), 2), p95_latency_s=round(pct(0.95), 2),
                                     avg_cost_usd_per_job_analysed=round(sum(cost) / len(cost), 6), p95_latency_s_per_job_analysed=round(pct(0.95), 2)),
            top_rejection_reasons=[RejectionReason(reason=r["reason"], count=r["n"]) for r in self.store.rejections(user.id)[:8]])

    async def list_memory(self, user: CurrentUser) -> MemoryList:
        await self._boot()
        items = []
        for m in self._memory.list_all(user.id):
            items.append(MemoryItem(memory_id=m["id"], kind="style" if m["kind"] == "style" else "outcome", text=m["text"],
                                    source=f"{m.get('rule', 'rule')}: {json.dumps(m.get('evidence', {}))[:100]}",
                                    created_at=_iso(m.get("created_at")), promoted=True, confidence=0.8))
        return MemoryList(items=items)

    async def delete_memory(self, user: CurrentUser, memory_id: str) -> None:
        await self._boot()
        if not self._memory.delete(user.id, memory_id):
            raise NotFound("memory item not found")

    # ------------------------------------------------------------------ onboarding / portfolio
    async def get_onboarding(self, user: CurrentUser) -> OnboardingState:
        opts = []
        for p in PERSONAS:
            pr = _profile(p)
            if pr:
                opts.append(PersonaOption(persona_id=p, display_name=pr.get("display_name", p), headline=pr.get("headline", ""),
                                          skills=pr.get("skills", [])[:8], hourly_rate_usd=int(pr.get("hourly_rate_usd", 0))))
        return OnboardingState(completed=user.onboarded, persona_id=user.persona_id, personas=opts)

    async def complete_onboarding(self, user: CurrentUser, req: OnboardingRequest) -> OnboardingState:
        cur = await self.get_settings(user)
        new = cur.model_copy(update={"hourly_rate_usd": req.hourly_rate_usd, "min_budget_usd": req.min_budget_usd,
                                     "weekly_connects_budget": req.weekly_connects_budget})
        self.store.put_settings(user.id, new.model_dump())
        return await self.get_onboarding(user)

    async def upload_portfolio(self, user: CurrentUser, filename: str, content_type: str, data: bytes) -> PortfolioFile:
        sha = hashlib.sha256(data).hexdigest()
        status = "failed"
        try:
            from rag.ingest.loaders import read_pdf_text
            from rag.retriever import add_document
            from rag.types import Document

            text = read_pdf_text(data) if filename.lower().endswith(".pdf") else data.decode("utf-8", errors="ignore")
            if text.strip():
                dtype = "cv" if "cv" in filename.lower() or filename.lower().endswith(".pdf") else "case_study"
                doc = Document(doc_id=f"upload:{sha[:16]}", persona=f"u-{user.id}", type=dtype, text=text, title=filename,
                               source=f"upload/{filename}", date=datetime.now(UTC).date().isoformat())
                await asyncio.to_thread(add_document, f"u-{user.id}", doc)
                status = "indexed"
        except Exception:  # noqa: BLE001 - a failed index must not lose the upload
            log.exception("portfolio indexing failed")
        return PortfolioFile(file_id=sha[:16], filename=filename, size_bytes=len(data), status=status, created_at=_iso(time.time()))

    # ------------------------------------------------------------------ health
    async def marketplace_health(self) -> MarketplaceStatus:
        await self._boot()
        mode = self.cfg.marketplace_mode
        gw = ToolGateway(self.cfg, user_id="health", servers=self._servers, transport=self._transport)
        ok = await gw.probe("marketplace")
        st = gw.status()
        return MarketplaceStatus(ok=ok, mode=mode, detail=st.get("message") or "", checked_at=datetime.now(UTC).isoformat())


def record_bid_result(store: RealStore, user_id: str, job_id: str, run_id: str, last: dict) -> None:
    """Persist the outcome of a bid run (run row, job summary, pending approval). Used by the API and the worker."""
    state = last.get("state", {}) or {}
    interrupted = bool(last.get("interrupted"))
    status = "awaiting_approval" if interrupted else STATUS_MAP.get(state.get("status", ""), "dead_letter")
    if last.get("type") == "error" and not state:
        status = "needs_attention"
    usage = last.get("usage") or {}
    run = store.get_run(user_id, run_id) or {}
    now = time.time()
    store.upsert_run(run_id, user_id, status=status, finished_at=now,
                     latency_ms=int((now - (run.get("started_at") or now)) * 1000),
                     total_tokens=int(usage.get("total_tokens", 0)), cost_usd=float(usage.get("total_cost_usd", 0)))
    job = state.get("job", {})
    dec = state.get("decision", {})
    summary = {"fit": state.get("fit_report", {}).get("score"), "risk": state.get("risk_report", {}).get("score"),
               "flags": state.get("risk_report", {}).get("flags", []), "is_scam": state.get("risk_report", {}).get("is_scam"),
               "injection": state.get("risk_report", {}).get("injection_detected"),
               "recommendation": dec.get("decision"), "price": state.get("price_quote", {}).get("amount"),
               "reason": state.get("status_reason")}
    jstatus = "drafted" if (interrupted or status == "submitted") else "skipped" if status == "skipped" else "analyzed"
    store.set_job(user_id, job_id, jstatus, run_id, job.get("title", job_id), job.get("category", ""), summary)
    if interrupted and last.get("pending"):
        store.put_approval(run_id, user_id, run_id, run_id, last["pending"].get("kind", "proposal"),
                           job.get("title", job_id), last["pending"])


async def build_runtime(cfg: Config) -> GraphRuntime:
    """Worker entry: a runtime for the persona-agnostic worker (per-user gateways are made per task)."""
    svc = RealServices(cfg)
    await svc._boot()
    return GraphRuntime(cfg, ToolGateway(cfg, user_id="worker", servers=svc._servers), llm=svc._llm, memory=svc._memory,
                        checkpointer=svc._checkpointer)


def build_user_repo():
    """Worker entry: the repo of active users, read from the API database."""
    from apps.api.config import load_config as load_app_config
    from apps.api.db import ProfileRow, UserRow, make_engine, make_session_factory

    factory = make_session_factory(make_engine(load_app_config().database_url))
    store = RealStore(os.getenv("REAL_STORE_DB", ROOT / "data" / "processed" / "real_store.sqlite"))

    class Repo:
        def active_users(self) -> list[dict]:
            with factory() as db:
                out = []
                for u in db.query(UserRow).filter(UserRow.onboarded.is_(True)).all():
                    prof = db.get(ProfileRow, u.id)
                    persona = u.persona_id if u.persona_id in PERSONAS else "ai_ml"
                    stored = store.get_settings(u.id)
                    searches = (stored or {}).get("saved_searches") or _profile(persona).get("saved_searches", [])
                    out.append({"user_id": u.id, "persona_id": persona,
                                "settings": {"min_project_budget_usd": (prof.min_budget_usd if prof else 300),
                                             "hourly_rate_usd": (prof.hourly_rate_usd if prof else 65)},
                                "saved_searches": searches})
                return out

        def record_run(self, user_id: str, job_id: str, thread_id: str, status: str, summary: dict) -> None:
            store.upsert_run(thread_id, user_id, job_id=job_id, thread_id=thread_id, status="running")
            record_bid_result(store, user_id, job_id, thread_id, summary.get("last", {}))

        def mark_scanned(self, user_id: str, ts: float) -> None:
            store.run("insert or replace into cursor values (?,?)", (f"scan:{user_id}", str(ts)))

        def last_scanned(self, user_id: str) -> float:
            r = store.get_cursor(f"scan:{user_id}")
            return float(r) if r else 0.0

    return Repo()
