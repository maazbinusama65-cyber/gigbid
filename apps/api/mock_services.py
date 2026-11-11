"""Fixture-backed Services implementation (GIGBID_SERVICES=mock, the default).

State is per user id (tenant isolation) and lives in process memory, so a pending approval survives a
page refresh exactly like it will with the real checkpointer. Streams are scripted with small delays.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

from agent.handoffs import ApprovalDecision, ApprovalRequest
from apps.api import mock_data as md
from apps.api.auth.deps import CurrentUser
from apps.api.errors import Conflict, NotFound
from apps.api.logging_setup import current_trace_id
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
    JobDetail,
    JobListResponse,
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
from apps.api.schemas.pipeline import (
    STAGES,
    MarketplaceEvent,
    PipelineBoard,
    PipelineCard,
    PipelineColumn,
)
from apps.api.schemas.proposals import ProposalStudio, RegenerateRequest
from apps.api.schemas.runs import (
    RunDetail,
    RunList,
    RunStep,
    RunSummary,
    TraceResponse,
    TraceSpan,
)
from apps.api.schemas.settings import (
    MemoryItem,
    MemoryList,
    OnboardingRequest,
    OnboardingState,
    PortfolioFile,
    SavedSearch,
    UserSettings,
    UserSettingsUpdate,
)

# node, label, model, tokens_in, tokens_out, duration_ms, parallel group
_STEP_TABLE: list[tuple[str, str, str | None, int, int, int, int]] = [
    ("job_analyst", "Job Analyst", "small-model", 1800, 420, 1400, 1),
    ("risk_assessor", "Risk Assessor", "small-model", 1100, 260, 900, 1),
    ("fit_matcher", "Fit Matcher", "small-model", 2600, 380, 2100, 1),
    ("decide", "Bid or skip", "small-model", 400, 90, 350, 2),
    ("pricing", "Pricing", "small-model", 900, 220, 800, 3),
    ("writer", "Proposal Writer", "large-model", 3200, 780, 4200, 4),
    ("verifier", "Claim Verifier", "small-model", 2400, 300, 1700, 5),
    ("critic", "Critic", "large-model", 2100, 260, 1500, 6),
    ("compliance", "Compliance", "small-model", 700, 120, 600, 7),
]
_LABELS = {row[0]: row[1] for row in _STEP_TABLE} | {"approval_gate": "Human approval", "submit": "Submit proposal"}
_RATES = {"small-model": (0.15, 0.6), "large-model": (2.5, 10.0)}
_COLUMN_LABELS = {
    "drafted": "Drafted", "submitted": "Submitted", "viewed": "Viewed", "replied": "Replied",
    "interview": "Interview", "hired": "Hired", "lost": "Lost",
}


def _cost(model: str | None, tin: int, tout: int) -> float:
    rin, rout = _RATES.get(model or "", (0, 0))
    return round((tin * rin + tout * rout) / 1_000_000, 5)


def _nodes_for(rec: str, is_scam: bool) -> list[str]:
    if is_scam:
        return ["job_analyst", "risk_assessor", "decide"]
    if rec == "bid":
        return [r[0] for r in _STEP_TABLE]
    return ["job_analyst", "risk_assessor", "fit_matcher", "decide"]


class _UserState:
    def __init__(self) -> None:
        self.job_status: dict[str, str] = {}
        self.job_run: dict[str, str] = {}
        self.job_approval: dict[str, str] = {}
        self.drafts: dict[str, Any] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.pipeline: list[dict[str, Any]] = md.seed_pipeline()
        self.events: list[dict[str, Any]] = md.seed_events()
        self.threads: dict[str, dict[str, Any]] = {t["thread_id"]: t for t in md.seed_threads()}
        self.memory: list[dict[str, Any]] = md.seed_memory()
        self.rejections: Counter[str] = Counter()
        self.portfolio: list[PortfolioFile] = []
        self.onboarding: dict[str, Any] = {}
        self.settings = UserSettings(
            saved_searches=[
                SavedSearch(search_id="ss_1", name="RAG + LangGraph", query="rag langgraph", category="NLP & LLM apps"),
                SavedSearch(search_id="ss_2", name="MLOps on Kubernetes", query="kubernetes mlops", category="MLOps",
                            interval_minutes=120),
            ]
        )


class MockServices:
    def __init__(self, delay_ms: int = 350, trace_url_template: str = "http://localhost:6006/trace/{trace_id}") -> None:
        self.delay_ms = delay_ms
        self.trace_url_template = trace_url_template
        self.degraded = False
        self._states: dict[str, _UserState] = {}

    # ------------------------------------------------------------------ mock controls (not in the Protocol)
    def set_degraded(self, value: bool) -> None:
        self.degraded = value

    def reset(self) -> None:
        self._states.clear()
        self.degraded = False

    # ------------------------------------------------------------------ state seeding
    def _state(self, user: CurrentUser) -> _UserState:
        st = self._states.get(user.id)
        if st is None:
            st = self._states[user.id] = _UserState()
            self._seed(st)
        self._settle(st)
        return st

    def _seed(self, st: _UserState) -> None:
        for d in md.JOB_DEFS:
            st.job_status[d["job_id"]] = d["status"] if d["status"] != "drafted" else "new"
        for jid, rid, hours in (("job_1001", "run_1001", 3), ("job_1002", "run_1002", 6), ("job_1003", "run_1003", 1),
                                ("job_1004", "run_1004", 5), ("job_1005", "run_1005", 11)):
            run = self._new_run(st, jid, run_id=rid, started=md.ago(hours=hours), trace_id=f"seed-trace-{jid[-4:]}")
            while run["script"]:
                self._emit(st, run, run["script"].pop(0), seeded=True)
        for jid, rid, status, title, note in (
            ("job_0871", "run_0990", "submitted", "Semantic search for a recipe app", ""),
            ("job_0866", "run_0985", "blocked", "RAG chatbot over HR policies",
             "Compliance blocked the draft: it promised a guaranteed outcome. You can edit and resubmit."),
            ("job_0842", "run_0980", "dead_letter", "Sentiment dashboard backend",
             "Marketplace returned 503 on submit 5 times; moved to the dead-letter queue. Retry from the worker UI."),
            ("job_0820", "run_0975", "rejected", "Voice-assistant prototype", "You rejected this draft: tone too formal."),
        ):
            st.runs[rid] = self._historical_run(rid, jid, title, status, note)

    def _historical_run(self, rid: str, jid: str, title: str, status: str, note: str) -> dict[str, Any]:
        nodes = _nodes_for("bid", False)
        stop = {"blocked": "compliance", "dead_letter": "submit", "rejected": "approval_gate"}.get(status)
        steps: list[RunStep] = []
        for n in nodes + (["approval_gate"] if stop in {"approval_gate", "submit"} else []) + (["submit"] if stop == "submit" else []):
            row = next((r for r in _STEP_TABLE if r[0] == n), None)
            tin, tout, ms, model = (row[3], row[4], row[5], row[2]) if row else (0, 0, 600, None)
            failed = status == "blocked" and n == "compliance"
            steps.append(RunStep(node=n, label=_LABELS[n], status="failed" if (failed or (status == "dead_letter" and n == "submit")) else "done",
                                 duration_ms=ms, tokens_in=tin, tokens_out=tout, cost_usd=_cost(model, tin, tout),
                                 model=model, summary=note if (failed or n == "submit") and note else ""))
        return dict(run_id=rid, job_id=jid, title=title, status=status, started_at=md.ago(days=3), finished_at=md.ago(days=3),
                    steps=steps, log=[], script=[], trace_id=f"seed-trace-{rid[-4:]}", approval_id=None,
                    notes=[note] if note else [], lock=asyncio.Lock(), created_mono=0.0, total_delay=0.0)

    # ------------------------------------------------------------------ runs: plan, emit, settle
    def _new_run(self, st: _UserState, job_id: str, run_id: str | None = None, started: str | None = None,
                 trace_id: str | None = None) -> dict[str, Any]:
        d = md.job_def(job_id)
        assert d is not None
        run_id = run_id or f"run_{uuid.uuid4().hex[:10]}"
        nodes = _nodes_for(d["rec"], bool(d.get("is_scam")))
        steps = [RunStep(node=n, label=_LABELS[n], status="pending",
                         model=next((r[2] for r in _STEP_TABLE if r[0] == n), None)) for n in nodes]
        if d["rec"] == "bid":
            steps.append(RunStep(node="approval_gate", label=_LABELS["approval_gate"], status="pending"))
        run = dict(run_id=run_id, job_id=job_id, title=d["title"], status="running", started_at=started or md.iso(md.now()),
                   finished_at=None, steps=steps, log=[], script=self._script(d, nodes), trace_id=trace_id or current_trace_id(),
                   approval_id=None, notes=[], lock=asyncio.Lock(), created_mono=time.monotonic(), total_delay=0.0)
        run["total_delay"] = sum(self._delay_s(t) for t in run["script"])
        st.runs[run_id] = run
        st.job_run[job_id] = run_id
        return run

    def _script(self, d: dict[str, Any], nodes: list[str]) -> list[dict[str, Any]]:
        by_node = {r[0]: r for r in _STEP_TABLE}
        script: list[dict[str, Any]] = []

        def end(n: str) -> dict[str, Any]:
            r = by_node[n]
            return dict(type="node_end", node=n, delay=1.0, data=dict(
                duration_ms=r[5], tokens_in=r[3], tokens_out=r[4], cost_usd=_cost(r[2], r[3], r[4]), model=r[2],
                summary=self._summary(n, d)))

        groups: dict[int, list[str]] = {}
        for n in nodes:
            groups.setdefault(by_node[n][6], []).append(n)
        for g in sorted(groups):
            members = groups[g]
            script += [dict(type="node_start", node=n, delay=0.4, data={"label": _LABELS[n]}) for n in members]
            if "writer" in members:
                letter, *_ = md.build_draft(d)[0].cover_letter.split("\n\n")
                words = letter.split(" ")
                for i in range(0, len(words), 6):
                    script.append(dict(type="token", node="writer", delay=0.25, data={"text": " ".join(words[i:i + 6]) + " "}))
            script += [end(n) for n in sorted(members, key=lambda m: by_node[m][5])]
            if g == 1 and self.degraded:
                script.append(dict(type="degraded", node="job_analyst", delay=0.3, data={
                    "service": "marketplace", "detail": "Client history unavailable; using the cached profile."}))
        if d["rec"] == "bid":
            script += [
                dict(type="node_start", node="approval_gate", delay=0.4, data={"label": _LABELS["approval_gate"]}),
                dict(type="interrupt", node="approval_gate", delay=0.5, data={"kind": "proposal", "job_id": d["job_id"]}),
                dict(type="done", node=None, delay=0.1, data={"status": "awaiting_approval"}),
            ]
        else:
            status, reason = (
                ("skipped", "Scam pattern detected; auto-skipped, no Connects spent.") if d.get("is_scam")
                else ("needs_attention", "Injection attempt in the post; review the sanitized analysis.") if d.get("injection")
                else ("skipped", f"Decision: {d['rec']}. No proposal drafted.")
            )
            script.append(dict(type="done", node=None, delay=0.1, data={"status": status, "decision": d["rec"], "reason": reason}))
        return script

    @staticmethod
    def _summary(node: str, d: dict[str, Any]) -> str:
        return {
            "job_analyst": f"Extracted {len(d['reqs'])} atomic requirements and {len(d['deliverables'])} deliverables.",
            "risk_assessor": f"Risk {d['risk']:.2f}; flags: {', '.join(d['flags']) or 'none'}.",
            "fit_matcher": f"Fit {d['fit']:.2f}; {sum(1 for r in d['reqs'] if r[2] >= 0.6)} of {len(d['reqs'])} requirements evidenced.",
            "decide": f"Decision: {d['rec']}.",
            "pricing": f"Quote ${d['price']} inside band; {d['connects']} Connects.",
            "writer": "Drafted cover letter with per-claim evidence ids.",
            "verifier": "Claims verified against evidence; unsupported claims removed.",
            "critic": "Critic score 0.86; no send-back needed.",
            "compliance": "No policy violations; no redactions needed.",
        }.get(node, "")

    def _delay_s(self, tpl: dict[str, Any]) -> float:
        return tpl["delay"] * self.delay_ms / 1000

    def _emit(self, st: _UserState, run: dict[str, Any], tpl: dict[str, Any], seeded: bool = False) -> dict[str, Any]:
        ev = {"type": tpl["type"], "node": tpl.get("node"), "ts": md.iso(md.now()), "data": dict(tpl["data"])}
        run["log"].append(ev)
        step = next((s for s in run["steps"] if s.node == ev["node"]), None)
        if ev["type"] == "node_start" and step:
            step.status, step.started_at = "running", ev["ts"]
        elif ev["type"] == "node_end" and step:
            dd = ev["data"]
            step.status, step.duration_ms = "done", dd["duration_ms"]
            step.tokens_in, step.tokens_out, step.cost_usd = dd["tokens_in"], dd["tokens_out"], dd["cost_usd"]
            step.summary = dd["summary"]
        elif ev["type"] == "interrupt":
            if step := next((s for s in run["steps"] if s.node == "approval_gate"), None):
                step.status = "interrupted"
            approval = self._create_approval(st, run)
            ev["data"]["approval_id"] = approval["approval_id"]
        elif ev["type"] == "done":
            run["status"] = ev["data"]["status"]
            if run["status"] == "awaiting_approval":
                ev["data"]["approval_id"] = run["approval_id"]
            else:
                run["finished_at"] = ev["ts"]
                st.job_status[run["job_id"]] = "skipped" if run["status"] == "skipped" and (md.job_def(run["job_id"]) or {}).get("is_scam") else "analyzed"
                if ev["data"].get("reason"):
                    run["notes"].append(ev["data"]["reason"])
        return ev

    def _settle(self, st: _UserState) -> None:
        """Fast-forward scripted runs nobody is streaming once their simulated time has elapsed."""
        now = time.monotonic()
        for run in st.runs.values():
            if run["script"] and now - run["created_mono"] > run["total_delay"] + 1.0:
                while run["script"]:
                    self._emit(st, run, run["script"].pop(0))

    def _create_approval(self, st: _UserState, run: dict[str, Any]) -> dict[str, Any]:
        jid = run["job_id"]
        d = md.job_def(jid)
        assert d is not None
        existing = st.job_approval.get(jid)
        if existing:
            return st.approvals[existing]
        approval_id = {"job_1001": "appr_1001", "job_1002": "appr_1002"}.get(jid, f"appr_{uuid.uuid4().hex[:8]}")
        draft, critic, compliance = md.build_draft(d)
        st.drafts[jid] = (draft, critic, compliance)
        req = ApprovalRequest(
            kind="proposal", thread_id=f"thr_{run['run_id']}", job_id=jid, draft=draft, evidence=md.build_evidence(d),
            risk=md.build_risk(d), price=md.build_price(d), dry_run=md.build_dry_run(d, draft), critic=critic,
            compliance=compliance,
        )
        item = dict(approval_id=approval_id, status="pending", created_at=md.iso(md.now()), decided_at=None,
                    run_id=run["run_id"], title=d["title"], request=req, decision=None)
        st.approvals[approval_id] = item
        st.job_approval[jid] = approval_id
        st.job_status[jid] = "drafted"
        run["approval_id"] = approval_id
        if not any(c["job_id"] == jid for c in st.pipeline):
            st.pipeline.insert(0, dict(proposal_id=f"pr_{jid[-4:]}", job_id=jid, title=d["title"],
                                       client_name=md.client_summary(d["client_id"]).name, stage="drafted",
                                       bid_amount=d["price"], connects_spent=0, updated_at=md.iso(md.now()),
                                       last_event="Draft waiting for your approval", thread_id=None))
        return item

    # ------------------------------------------------------------------ jobs
    def _summary_for(self, st: _UserState, d: dict[str, Any]) -> JobSummary:
        status = st.job_status.get(d["job_id"], "new")
        return JobSummary(
            job_id=d["job_id"], title=d["title"], category=d["category"], client_name=md.client_summary(d["client_id"]).name,
            budget=md.build_posting(d).budget, posted_at=md.ago(hours=d["posted_h"]), fit_score=d["fit"], risk_score=d["risk"],
            risk_flags=d["flags"], is_scam=bool(d.get("is_scam")), injection_detected=bool(d.get("injection")),
            recommendation=d["rec"], suggested_price=d["price"], connects_cost=d["connects"],
            status=status, top_skills=d["skills"][:4], run_id=st.job_run.get(d["job_id"]),  # type: ignore[arg-type]
        )

    async def list_jobs(self, user: CurrentUser, *, q: str | None = None, category: str | None = None,
                        min_fit: float | None = None, include_skipped: bool = False, sort: str = "fit") -> JobListResponse:
        st = self._state(user)
        rows = [self._summary_for(st, d) for d in md.JOB_DEFS]
        if q:
            needle = q.lower()
            rows = [r for r in rows if needle in r.title.lower() or any(needle in s.lower() for s in r.top_skills)
                    or needle in (md.job_def(r.job_id) or {}).get("description", "").lower()]
        if category:
            rows = [r for r in rows if r.category == category]
        if min_fit is not None:
            rows = [r for r in rows if (r.fit_score or 0) >= min_fit]
        if not include_skipped:
            rows = [r for r in rows if r.status != "skipped"]
        key = {"fit": lambda r: -(r.fit_score or 0), "posted": lambda r: r.posted_at,
               "budget": lambda r: -(r.budget.max or 0)}.get(sort, lambda r: -(r.fit_score or 0))
        rows.sort(key=key, reverse=(sort == "posted"))
        return JobListResponse(jobs=rows, total=len(rows), marketplace_degraded=self.degraded,
                               categories=sorted({d["category"] for d in md.JOB_DEFS}))

    def _def(self, job_id: str) -> dict[str, Any]:
        d = md.job_def(job_id)
        if d is None:
            raise NotFound(f"Job {job_id} not found")
        return d

    async def get_job_detail(self, user: CurrentUser, job_id: str) -> JobDetail:
        st = self._state(user)
        d = self._def(job_id)
        status = st.job_status.get(job_id, "new")
        analyzed = status in {"analyzed", "drafted", "skipped"}
        detail = JobDetail(
            job=md.build_posting(d), client=md.client_summary(d["client_id"]), risk=md.build_risk(d),
            status=status, latest_run_id=st.job_run.get(job_id), approval_id=st.job_approval.get(job_id),  # type: ignore[arg-type]
            sanitized_notes=d.get("notes", []),
        )
        if analyzed:
            detail = detail.model_copy(update=dict(spec=md.build_spec(d), fit=md.build_fit(d), evidence=md.build_evidence(d),
                                                   price=md.build_price(d), decision=md.build_decision(d)))
        return detail

    async def analyze_job(self, user: CurrentUser, job_id: str) -> AnalyzeResponse:
        st = self._state(user)
        self._def(job_id)
        existing = st.job_run.get(job_id)
        if existing and st.runs[existing]["status"] in {"running", "awaiting_approval"}:
            return AnalyzeResponse(run_id=existing, job_id=job_id, status="running")
        if st.job_status.get(job_id) == "drafted" and job_id in st.job_approval:
            return AnalyzeResponse(run_id=st.job_run[job_id], job_id=job_id, status="running")
        run = self._new_run(st, job_id)
        st.job_status[job_id] = "analyzing"
        return AnalyzeResponse(run_id=run["run_id"], job_id=job_id, status="queued")

    async def skip_job(self, user: CurrentUser, job_id: str, reason: str) -> SkipResponse:
        st = self._state(user)
        self._def(job_id)
        st.job_status[job_id] = "skipped"
        if reason:
            st.rejections[f"Skipped: {reason}"] += 1
        return SkipResponse(job_id=job_id)

    # ------------------------------------------------------------------ studio
    def _studio(self, st: _UserState, job_id: str) -> ProposalStudio:
        d = self._def(job_id)
        if job_id not in st.drafts:
            raise NotFound("No draft yet for this job; run the analysis first")
        draft, critic, compliance = st.drafts[job_id]
        approval = st.approvals.get(st.job_approval.get(job_id, ""))
        pool = md.evidence_pool()
        return ProposalStudio(
            job_id=job_id, job_title=d["title"], draft=draft, paragraphs=draft.cover_letter.split("\n\n"),
            screening_questions=d["questions"], evidence=[pool[i] for i in draft.evidence_ids if i in pool], critic=critic,
            compliance=compliance, risk=md.build_risk(d), price=md.build_price(d), dry_run=md.build_dry_run(d, draft),
            approval_id=approval["approval_id"] if approval else None, approval_status=approval["status"] if approval else None,
            marketplace_degraded=self.degraded,
        )

    async def get_proposal_studio(self, user: CurrentUser, job_id: str) -> ProposalStudio:
        return self._studio(self._state(user), job_id)

    async def regenerate_paragraph(self, user: CurrentUser, job_id: str, req: RegenerateRequest) -> ProposalStudio:
        st = self._state(user)
        studio = self._studio(st, job_id)
        d = self._def(job_id)
        approval = st.approvals.get(st.job_approval.get(job_id, ""))
        if approval and approval["status"] != "pending":
            raise Conflict("This draft was already decided")
        paragraphs = list(studio.paragraphs)
        if req.paragraph_index >= len(paragraphs):
            raise NotFound("Paragraph index out of range")
        draft = studio.draft
        old = paragraphs[req.paragraph_index]
        new = md.ALT_PARAGRAPHS[(draft.revision + req.paragraph_index) % len(md.ALT_PARAGRAPHS)]
        if req.instruction:
            new = f"{new} (Adjusted per your note: {req.instruction.strip()[:120]}.)"
        paragraphs[req.paragraph_index] = new
        claims = [c for c in draft.claims if c.text not in old]  # claims living in the replaced paragraph are re-checked
        new_draft = draft.model_copy(update=dict(cover_letter="\n\n".join(paragraphs), claims=claims, revision=draft.revision + 1))
        st.drafts[job_id] = (new_draft, *st.drafts[job_id][1:])
        if approval:
            approval["request"] = approval["request"].model_copy(
                update=dict(draft=new_draft, dry_run=md.build_dry_run(d, new_draft)))
        return self._studio(st, job_id)

    # ------------------------------------------------------------------ approvals
    def _item(self, a: dict[str, Any]) -> ApprovalItem:
        return ApprovalItem(approval_id=a["approval_id"], status=a["status"], created_at=a["created_at"],
                            decided_at=a["decided_at"], run_id=a["run_id"], title=a["title"], request=a["request"],
                            decision=a["decision"])

    def _ensure_message_approvals(self, st: _UserState) -> None:
        for t in st.threads.values():
            aid = t["approval_id"]
            if aid in st.approvals or not t.get("reply"):
                continue
            ev = md.evidence_pool()
            req = ApprovalRequest(kind="message", thread_id=t["thread_id"], job_id=t.get("job_id"),
                                  draft={"text": t["reply"], "to": t["client_name"], "intent": t["intent"]},
                                  evidence=[ev[i] for i in t["evidence"]])
            st.approvals[aid] = dict(approval_id=aid, status="pending", created_at=md.ago(minutes=20), decided_at=None,
                                     run_id=None, title=f"Reply to {t['client_name']}", request=req, decision=None)

    async def list_approvals(self, user: CurrentUser, status: str | None = None) -> ApprovalList:
        st = self._state(user)
        self._ensure_message_approvals(st)
        items = sorted(st.approvals.values(), key=lambda a: a["created_at"], reverse=True)
        pending = sum(1 for a in items if a["status"] == "pending")
        if status:
            items = [a for a in items if a["status"] == status]
        return ApprovalList(approvals=[self._item(a) for a in items], pending_count=pending)

    async def decide_approval(self, user: CurrentUser, approval_id: str, decision: ApprovalDecision) -> DecisionResult:
        st = self._state(user)
        self._ensure_message_approvals(st)
        a = st.approvals.get(approval_id)
        if a is None:
            raise NotFound(f"Approval {approval_id} not found")
        if a["status"] != "pending":
            raise Conflict(f"Approval already {a['status']}")
        req: ApprovalRequest = a["request"]
        a["decision"], a["decided_at"] = decision, md.iso(md.now())
        a["status"] = {"approve": "approved", "edit": "edited", "reject": "rejected"}[decision.action]
        if req.kind == "message":
            return self._decide_message_item(st, a, decision)
        return self._decide_proposal(st, a, decision)

    def _decide_proposal(self, st: _UserState, a: dict[str, Any], decision: ApprovalDecision) -> DecisionResult:
        req: ApprovalRequest = a["request"]
        jid = req.job_id or ""
        d = md.job_def(jid) or {}
        run = st.runs.get(a["run_id"] or "")
        card = next((c for c in st.pipeline if c["job_id"] == jid), None)
        if decision.action == "reject":
            reason = (decision.reason or "").strip()
            st.rejections[reason] += 1
            st.memory.insert(0, dict(memory_id=f"mem_{uuid.uuid4().hex[:6]}", kind="preference", text=f"Rejected a draft: {reason}",
                                     source=f"rejection on {jid}", created_at=md.iso(md.now()), promoted=False, confidence=0.4))
            if card:
                st.pipeline.remove(card)
            self._finish_run(st, run, "rejected", f"You rejected this draft: {reason}")
            st.job_status[jid] = "analyzed"
            return DecisionResult(approval_id=a["approval_id"], status="rejected", run_id=a["run_id"],
                                  message="Draft rejected. Nothing was sent and no Connects were spent.")
        if decision.action == "edit":
            text = decision.edited_text or ""
            draft = req.draft.model_copy(update=dict(cover_letter=text, revision=req.draft.revision + 1))  # type: ignore[union-attr]
            if decision.edited_answers is not None:
                draft = draft.model_copy(update=dict(screening_answers=decision.edited_answers))
            a["request"] = req.model_copy(update=dict(draft=draft, dry_run=md.build_dry_run(d, draft)))
            st.drafts[jid] = (draft, *st.drafts[jid][1:])
            st.memory.insert(0, dict(memory_id=f"mem_{uuid.uuid4().hex[:6]}", kind="style", text="Edited a draft before sending (candidate for the style memory).",
                                     source=f"edit on {jid}", created_at=md.iso(md.now()), promoted=False, confidence=0.45))
        if self.degraded:
            if card:
                card["last_event"] = "Approved; queued because the marketplace is unavailable"
            self._finish_run(st, run, "needs_attention", "Approved, but the marketplace was unavailable. The send is queued for retry.")
            return DecisionResult(approval_id=a["approval_id"], status=a["status"], run_id=a["run_id"], submitted=False,
                                  queued=True, message="Marketplace unavailable. Your approval is saved and the send will retry automatically.")
        proposal_id = card["proposal_id"] if card else f"pr_{uuid.uuid4().hex[:6]}"
        if card:
            card.update(stage="submitted", connects_spent=d.get("connects", 0), updated_at=md.iso(md.now()),
                        last_event="Submitted, awaiting view")
        self._finish_run(st, run, "submitted", "")
        return DecisionResult(approval_id=a["approval_id"], status=a["status"], run_id=a["run_id"], submitted=True,
                              proposal_id=proposal_id, connects_spent=d.get("connects", 0),
                              message=f"Proposal submitted. {d.get('connects', 0)} Connects spent.")

    def _finish_run(self, st: _UserState, run: dict[str, Any] | None, status: str, note: str) -> None:
        if run is None:
            return
        if status == "submitted":
            run["log"] += [
                dict(type="node_start", node="submit", ts=md.iso(md.now()), data={"label": _LABELS["submit"], "resumed": True}),
                dict(type="node_end", node="submit", ts=md.iso(md.now()), data={"duration_ms": 640, "summary": "Submitted via marketplace MCP (idempotent)."}),
                dict(type="done", node=None, ts=md.iso(md.now()), data={"status": "submitted"}),
            ]
            run["steps"].append(RunStep(node="submit", label=_LABELS["submit"], status="done", duration_ms=640, summary="Submitted via marketplace MCP."))
        else:
            run["log"].append(dict(type="done", node=None, ts=md.iso(md.now()), data={"status": status, "reason": note}))
        for s in run["steps"]:
            if s.status == "interrupted":
                s.status = "done" if status == "submitted" else "skipped"
        run["status"], run["finished_at"] = status, md.iso(md.now())
        if note:
            run["notes"].append(note)

    # ------------------------------------------------------------------ pipeline
    async def pipeline_board(self, user: CurrentUser) -> PipelineBoard:
        st = self._state(user)
        cols = [PipelineColumn(stage=s, label=_COLUMN_LABELS[s],
                               cards=[PipelineCard(**c) for c in sorted(st.pipeline, key=lambda c: c["updated_at"], reverse=True)
                                      if c["stage"] == s]) for s in STAGES]
        return PipelineBoard(columns=cols, recent_events=[MarketplaceEvent(**e) for e in st.events[:6]],
                             marketplace_degraded=self.degraded, updated_at=md.iso(md.now()))

    # ------------------------------------------------------------------ messages
    def _thread_summary(self, t: dict[str, Any]) -> ThreadSummary:
        last_who, last_body, hrs = t["messages"][-1]
        return ThreadSummary(
            thread_id=t["thread_id"], client_name=t["client_name"], job_title=t["job_title"], last_message=last_body[:140],
            last_message_at=md.ago(hours=hrs), unread=t["unread"], intent=t["intent"], status=t["status"],
            has_suggested_reply=bool(t.get("reply")) and t["status"] == "needs_reply", injection_detected=t["injection"])

    async def list_threads(self, user: CurrentUser) -> ThreadList:
        st = self._state(user)
        return ThreadList(threads=[self._thread_summary(t) for t in st.threads.values()], marketplace_degraded=self.degraded)

    def _thread(self, st: _UserState, thread_id: str) -> dict[str, Any]:
        t = st.threads.get(thread_id)
        if t is None:
            raise NotFound(f"Thread {thread_id} not found")
        return t

    async def get_thread(self, user: CurrentUser, thread_id: str) -> ThreadDetail:
        st = self._state(user)
        t = self._thread(st, thread_id)
        t["unread"] = False
        msgs = [ChatMessage(message_id=f"{thread_id}_m{i}", sender=who, body=body, ts=md.ago(hours=h),
                            flagged=t["injection"] and who == "client")
                for i, (who, body, h) in enumerate(t["messages"])]
        reply = None
        if t.get("reply") and t["status"] == "needs_reply":
            reply = SuggestedReply(approval_id=t["approval_id"], text=t["reply"], intent=t["intent"], rationale=t["rationale"],
                                   evidence_ids=t["evidence"])
        slots = self._slots() if t["slots"] else []
        note = ("The client message contained an embedded instruction and a payment request. The instruction was ignored; "
                "nothing is sent without your approval.") if t["injection"] else ""
        return ThreadDetail(thread=self._thread_summary(t), messages=msgs, suggested_reply=reply, slots=slots,
                            job_id=t.get("job_id"), safety_note=note)

    @staticmethod
    def _slots() -> list[InterviewSlot]:
        base = md.now().replace(hour=15, minute=0, second=0, microsecond=0) + md.timedelta(days=2)
        out = []
        for i, (off, label) in enumerate(((0, "Thu 15:00 UTC"), (1, "Thu 16:30 UTC"), (24, "Fri 10:00 UTC"))):
            start = base + md.timedelta(hours=off, minutes=30 * (1 if i == 1 else 0))
            out.append(InterviewSlot(slot_id=f"slot_{i + 1}", start=md.iso(start), end=md.iso(start + md.timedelta(minutes=30)), label=label))
        return out

    async def decide_message(self, user: CurrentUser, thread_id: str, req: MessageDecisionRequest) -> MessageDecisionResult:
        st = self._state(user)
        t = self._thread(st, thread_id)
        decision = ApprovalDecision(action=req.action, edited_text=req.edited_text, reason=req.reason)
        self._ensure_message_approvals(st)
        a = st.approvals.get(t["approval_id"])
        if a is None or a["status"] != "pending":
            raise Conflict("No pending reply on this thread")
        a["decision"], a["decided_at"] = decision, md.iso(md.now())
        a["status"] = {"approve": "approved", "edit": "edited", "reject": "rejected"}[req.action]
        res = self._decide_message_item(st, a, decision, slot_id=req.slot_id)
        return MessageDecisionResult(thread_id=thread_id, status="rejected" if req.action == "reject" else ("queued" if res.queued else "sent"),
                                     interview_hold=next((s for s in self._slots() if s.slot_id == req.slot_id), None) if req.slot_id else None,
                                     message=res.message)

    def _decide_message_item(self, st: _UserState, a: dict[str, Any], decision: ApprovalDecision, slot_id: str | None = None) -> DecisionResult:
        t = st.threads[a["request"].thread_id]
        if decision.action == "reject":
            t["status"] = "needs_reply"
            t["reply"] = None
            return DecisionResult(approval_id=a["approval_id"], status="rejected", message="Suggested reply discarded. Nothing sent.")
        if self.degraded:
            return DecisionResult(approval_id=a["approval_id"], status=a["status"], queued=True,
                                  message="Marketplace unavailable. The reply is queued and will send when it is back.")
        body = decision.edited_text or t["reply"]
        t["messages"].append(("freelancer", body, 0))
        t["status"] = "interview_scheduled" if slot_id else "awaiting_client"
        t["reply"] = None
        return DecisionResult(approval_id=a["approval_id"], status=a["status"], submitted=True, message="Reply sent.")

    # ------------------------------------------------------------------ runs
    def _run_summary(self, r: dict[str, Any]) -> RunSummary:
        steps: list[RunStep] = r["steps"]
        tokens = sum(s.tokens_in + s.tokens_out for s in steps)
        latency = sum(s.duration_ms or 0 for s in steps) - 1800  # parallel group overlap
        return RunSummary(run_id=r["run_id"], job_id=r["job_id"], title=r["title"], status=r["status"], started_at=r["started_at"],
                          finished_at=r["finished_at"], total_tokens=tokens, cost_usd=round(sum(s.cost_usd for s in steps), 5),
                          latency_ms=max(latency, 0), trace_id=r["trace_id"])

    def _run(self, st: _UserState, run_id: str) -> dict[str, Any]:
        r = st.runs.get(run_id)
        if r is None:
            raise NotFound(f"Run {run_id} not found")
        return r

    async def list_runs(self, user: CurrentUser) -> RunList:
        st = self._state(user)
        runs = sorted(st.runs.values(), key=lambda r: r["started_at"], reverse=True)
        return RunList(runs=[self._run_summary(r) for r in runs])

    def _trace_url(self, trace_id: str) -> str:
        return self.trace_url_template.format(trace_id=trace_id)

    async def get_run(self, user: CurrentUser, run_id: str) -> RunDetail:
        st = self._state(user)
        r = self._run(st, run_id)
        return RunDetail(summary=self._run_summary(r), steps=[s.model_copy() for s in r["steps"]],
                         trace_url=self._trace_url(r["trace_id"]), approval_id=r["approval_id"], notes=list(r["notes"]))

    async def stream_run(self, user: CurrentUser, run_id: str) -> AsyncIterator[dict]:  # type: ignore[override]
        st = self._state(user)
        run = self._run(st, run_id)
        i = 0
        while True:
            if i < len(run["log"]):
                yield run["log"][i]
                i += 1
                continue
            if not run["script"]:
                return
            async with run["lock"]:
                if i < len(run["log"]) or not run["script"]:
                    continue
                tpl = run["script"][0]
                await asyncio.sleep(self._delay_s(tpl))
                run["script"].pop(0)
                self._emit(st, run, tpl)

    async def get_trace(self, user: CurrentUser, run_id: str) -> TraceResponse:
        st = self._state(user)
        r = self._run(st, run_id)
        spans = [TraceSpan(span_id="s0", name="bid_graph", kind="graph", start_ms=0, duration_ms=0, attributes={"run_id": run_id})]
        t = 0
        total_cost = 0.0
        for i, s in enumerate(r["steps"], start=1):
            dur = s.duration_ms or 0
            spans.append(TraceSpan(span_id=f"s{i}", parent_id="s0", name=s.node, kind="node", start_ms=t, duration_ms=dur,
                                   tokens_in=s.tokens_in, tokens_out=s.tokens_out, cost_usd=s.cost_usd, attributes={"model": s.model or ""}))
            if s.model:
                spans.append(TraceSpan(span_id=f"s{i}l", parent_id=f"s{i}", name=f"llm:{s.model}", kind="llm", start_ms=t, duration_ms=int(dur * 0.9),
                                       tokens_in=s.tokens_in, tokens_out=s.tokens_out, cost_usd=s.cost_usd))
            if s.node == "fit_matcher":
                spans.append(TraceSpan(span_id=f"s{i}m", parent_id=f"s{i}", name="portfolio.search_evidence", kind="mcp",
                                       start_ms=t, duration_ms=180, attributes={"trace_id": r["trace_id"], "k": 5}))
            if s.node == "submit":
                spans.append(TraceSpan(span_id=f"s{i}m", parent_id=f"s{i}", name="marketplace.submit_proposal", kind="mcp",
                                       start_ms=t, duration_ms=420, attributes={"trace_id": r["trace_id"], "idempotency_key": run_id}))
            total_cost += s.cost_usd
            if s.node not in {"job_analyst", "risk_assessor"}:
                t += dur
        spans[0] = spans[0].model_copy(update=dict(duration_ms=t))
        return TraceResponse(trace_id=r["trace_id"], run_id=run_id, url=self._trace_url(r["trace_id"]), spans=spans,
                             total_cost_usd=round(total_cost, 5), total_ms=t)

    # ------------------------------------------------------------------ analytics / settings / memory
    async def analytics_summary(self, user: CurrentUser) -> AnalyticsSummary:
        st = self._state(user)
        rows = [("NLP & LLM apps", 31, 14, 5), ("ML Engineering", 22, 9, 4), ("MLOps", 12, 4, 2),
                ("Data Analytics", 9, 2, 0), ("Computer Vision", 6, 1, 0)]
        cats = [CategoryStat(category=c, proposals_sent=n, replies=r, hires=h, reply_rate=round(r / n, 3), hire_rate=round(h / n, 3))
                for c, n, r, h in rows]
        weeks = [("W-7", 40, 3, 1), ("W-6", 52, 5, 1), ("W-5", 44, 4, 2), ("W-4", 60, 7, 2), ("W-3", 56, 6, 1), ("W-2", 48, 5, 2),
                 ("W-1", 60, 8, 3), ("This week", 28, 3, 1)]
        reasons = Counter({"Tone too formal": 7, "Price too high": 5, "Claim not in portfolio": 4, "Wrong client fit": 3,
                           "Opening too generic": 2}) + st.rejections
        sent = sum(c.proposals_sent for c in cats)
        return AnalyticsSummary(
            is_sample=True,
            sample_note="Sample data for the demo. These are NOT measured outcomes; real numbers come from the marketplace event log.",
            period_label="Last 8 weeks (sample)",
            totals={"proposals_sent": sent, "replies": sum(c.replies for c in cats), "hires": sum(c.hires for c in cats),
                    "connects_spent": sum(w[1] for w in weeks)},
            by_category=cats,
            connects_vs_outcomes=[ConnectsPoint(period=p, connects_spent=c, replies=r, hires=h) for p, c, r, h in weeks],
            cost_latency=CostLatency(proposals_measured=80, avg_cost_usd_per_proposal=0.031, p50_latency_s=14.2, p95_latency_s=27.9,
                                     avg_cost_usd_per_job_analysed=0.006, p95_latency_s_per_job_analysed=5.1),
            top_rejection_reasons=[RejectionReason(reason=k, count=v) for k, v in reasons.most_common(6)],
        )

    async def get_settings(self, user: CurrentUser) -> UserSettings:
        return self._state(user).settings

    async def update_settings(self, user: CurrentUser, update: UserSettingsUpdate) -> UserSettings:
        st = self._state(user)
        st.settings = st.settings.model_copy(update=update.model_dump(exclude_unset=True, exclude_none=True))
        return st.settings

    async def list_memory(self, user: CurrentUser) -> MemoryList:
        return MemoryList(items=[MemoryItem(**m) for m in self._state(user).memory])

    async def delete_memory(self, user: CurrentUser, memory_id: str) -> None:
        st = self._state(user)
        before = len(st.memory)
        st.memory = [m for m in st.memory if m["memory_id"] != memory_id]
        if len(st.memory) == before:
            raise NotFound(f"Memory item {memory_id} not found")

    # ------------------------------------------------------------------ onboarding
    async def get_onboarding(self, user: CurrentUser) -> OnboardingState:
        st = self._state(user)
        o = st.onboarding
        return OnboardingState(completed=user.onboarded, persona_id=o.get("persona_id") or user.persona_id, personas=md.PERSONAS,
                               marketplace=o.get("marketplace", "gigsim"), hourly_rate_usd=o.get("hourly_rate_usd"),
                               min_budget_usd=o.get("min_budget_usd"), weekly_connects_budget=o.get("weekly_connects_budget"),
                               portfolio_files=list(st.portfolio))

    async def complete_onboarding(self, user: CurrentUser, req: OnboardingRequest) -> OnboardingState:
        st = self._state(user)
        st.onboarding = req.model_dump()
        st.settings = st.settings.model_copy(update=dict(hourly_rate_usd=req.hourly_rate_usd, min_budget_usd=req.min_budget_usd,
                                                         weekly_connects_budget=req.weekly_connects_budget))
        return await self.get_onboarding(user)

    async def upload_portfolio(self, user: CurrentUser, filename: str, content_type: str, data: bytes) -> PortfolioFile:
        st = self._state(user)
        f = PortfolioFile(file_id=uuid.uuid4().hex[:12], filename=filename, size_bytes=len(data), status="indexed", created_at=md.iso(md.now()))
        st.portfolio.append(f)
        return f

    # ------------------------------------------------------------------ health
    async def marketplace_health(self) -> MarketplaceStatus:
        return MarketplaceStatus(ok=not self.degraded, mode="mock", checked_at=md.iso(md.now()),
                                 detail="GigSim unreachable (simulated outage)" if self.degraded else "ok")
