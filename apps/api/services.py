"""The seam between the web API and the agent core.

Every business endpoint calls exactly one method here. ``MockServices`` (apps/api/mock_services.py)
is fixture-backed; ``RealServices`` (apps/api/real_services.py, written by the agent-core owner)
drives the LangGraph graphs, the marketplace MCP server and the portfolio store.

Contract notes for implementers
* Every method receives the authenticated ``CurrentUser`` first and MUST scope all reads/writes to
  ``user.id`` (tenant isolation). Raise ``apps.api.errors.NotFound`` for ids that belong to someone else.
* ``apps.api.logging_setup.current_trace_id()`` returns the request trace id; pass it to the graph
  config so the same id shows up in LangSmith/Langfuse, MCP calls and the audit log.
* ``stream_run`` yields dicts shaped like ``schemas.runs.RunEvent`` (type, node, ts, data).
* ``decide_approval`` resumes the interrupted LangGraph thread (``Command(resume=decision)``).
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from agent.handoffs import ApprovalDecision
from apps.api.auth.deps import CurrentUser
from apps.api.config import AppConfig
from apps.api.schemas.analytics import AnalyticsSummary
from apps.api.schemas.approvals import ApprovalList, DecisionResult
from apps.api.schemas.common import MarketplaceStatus
from apps.api.schemas.jobs import AnalyzeResponse, JobDetail, JobListResponse, SkipResponse
from apps.api.schemas.messages import (
    MessageDecisionRequest,
    MessageDecisionResult,
    ThreadDetail,
    ThreadList,
)
from apps.api.schemas.pipeline import PipelineBoard
from apps.api.schemas.proposals import ProposalStudio, RegenerateRequest
from apps.api.schemas.runs import RunDetail, RunList, TraceResponse
from apps.api.schemas.settings import (
    MemoryList,
    OnboardingRequest,
    OnboardingState,
    PortfolioFile,
    UserSettings,
    UserSettingsUpdate,
)


@runtime_checkable
class Services(Protocol):
    # --- jobs -------------------------------------------------------------------------
    async def list_jobs(
        self,
        user: CurrentUser,
        *,
        q: str | None = None,
        category: str | None = None,
        min_fit: float | None = None,
        include_skipped: bool = False,
        sort: str = "fit",
    ) -> JobListResponse: ...

    async def get_job_detail(self, user: CurrentUser, job_id: str) -> JobDetail: ...

    async def analyze_job(self, user: CurrentUser, job_id: str) -> AnalyzeResponse: ...

    async def skip_job(self, user: CurrentUser, job_id: str, reason: str) -> SkipResponse: ...

    # --- proposals / approvals --------------------------------------------------------
    async def get_proposal_studio(self, user: CurrentUser, job_id: str) -> ProposalStudio: ...

    async def regenerate_paragraph(
        self, user: CurrentUser, job_id: str, req: RegenerateRequest
    ) -> ProposalStudio: ...

    async def list_approvals(
        self, user: CurrentUser, status: str | None = None
    ) -> ApprovalList: ...

    async def decide_approval(
        self, user: CurrentUser, approval_id: str, decision: ApprovalDecision
    ) -> DecisionResult: ...

    # --- pipeline / messages ----------------------------------------------------------
    async def pipeline_board(self, user: CurrentUser) -> PipelineBoard: ...

    async def list_threads(self, user: CurrentUser) -> ThreadList: ...

    async def get_thread(self, user: CurrentUser, thread_id: str) -> ThreadDetail: ...

    async def decide_message(
        self, user: CurrentUser, thread_id: str, req: MessageDecisionRequest
    ) -> MessageDecisionResult: ...

    # --- runs -------------------------------------------------------------------------
    async def list_runs(self, user: CurrentUser) -> RunList: ...

    async def get_run(self, user: CurrentUser, run_id: str) -> RunDetail: ...

    def stream_run(self, user: CurrentUser, run_id: str) -> AsyncIterator[dict]: ...

    async def get_trace(self, user: CurrentUser, run_id: str) -> TraceResponse: ...

    # --- analytics / settings / memory ------------------------------------------------
    async def analytics_summary(self, user: CurrentUser) -> AnalyticsSummary: ...

    async def get_settings(self, user: CurrentUser) -> UserSettings: ...

    async def update_settings(
        self, user: CurrentUser, update: UserSettingsUpdate
    ) -> UserSettings: ...

    async def list_memory(self, user: CurrentUser) -> MemoryList: ...

    async def delete_memory(self, user: CurrentUser, memory_id: str) -> None: ...

    # --- onboarding / portfolio -------------------------------------------------------
    async def get_onboarding(self, user: CurrentUser) -> OnboardingState: ...

    async def complete_onboarding(
        self, user: CurrentUser, req: OnboardingRequest
    ) -> OnboardingState: ...

    async def upload_portfolio(
        self, user: CurrentUser, filename: str, content_type: str, data: bytes
    ) -> PortfolioFile: ...

    # --- health -----------------------------------------------------------------------
    async def marketplace_health(self) -> MarketplaceStatus: ...


def build_services(config: AppConfig) -> Services:
    """Pick the implementation. ``real`` is imported lazily so mock mode has no agent-core deps."""
    mode = config.services_mode
    if mode == "mock":
        from apps.api.mock_services import MockServices

        return MockServices(
            delay_ms=config.mock_delay_ms, trace_url_template=config.trace_url_template
        )
    if mode == "real":
        from apps.api.real_services import RealServices  # written by the agent-core owner

        return RealServices()
    raise ValueError(f"GIGBID_SERVICES must be 'mock' or 'real', got {mode!r}")
