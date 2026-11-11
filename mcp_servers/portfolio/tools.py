"""Portfolio tools. All read-only: they can never change the portfolio or reach the network."""
from __future__ import annotations

from typing import Annotated

import anyio.to_thread
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .models import CaseStudy, EvidenceFilters, PortfolioIdParam, SearchEvidenceResult, SkillList
from .service import PortfolioService
from .store import NotFound

READ_ONLY = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def register_tools(mcp: FastMCP, svc: PortfolioService) -> None:
    @mcp.tool(title="Search portfolio evidence", annotations=READ_ONLY)
    async def search_evidence(
        requirement: Annotated[
            str,
            Field(min_length=3, max_length=500,
                  description="One atomic job requirement or question, e.g. 'built a RAG pipeline "
                              "over PDFs'. Search once per requirement, not once per job."),
        ],
        k: Annotated[int, Field(ge=1, le=20, description="How many evidence items to return.")] = 5,
        filters: Annotated[
            EvidenceFilters | None,
            Field(description="Optional narrowing by type, project, skills, outcome or date."),
        ] = None,
        portfolio_id: PortfolioIdParam = None,
    ) -> SearchEvidenceResult:
        """Find the freelancer's own past work that proves one requirement.

        Returns ranked evidence items (case study, README, code, review, CV, or a past proposal
        with its won/replied/ignored outcome), each with id, source, date and the passage text.
        Use the returned ids as citations. Returns an empty list when nothing supports the
        requirement; never invents evidence. For the full text of one project use get_case_study.
        """
        try:
            # retrieval is CPU-bound (embeddings + cross-encoder): run it off the event loop so
            # concurrent tools (and other agents sharing an in-process server) are never blocked
            return await anyio.to_thread.run_sync(
                svc.search_evidence, requirement, k, filters.to_dict() if filters else None, portfolio_id
            )
        except NotFound as exc:
            raise ToolError(f"not_found: {exc}") from exc

    @mcp.tool(title="Get a case study", annotations=READ_ONLY)
    def get_case_study(
        id: Annotated[
            str,
            Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_\-]+$",
                  description="Project id, as found in search_evidence results (project_id)."),
        ],
        portfolio_id: PortfolioIdParam = None,
    ) -> CaseStudy:
        """Load the full case study for one project: markdown text, skills, industry, outcome,
        client reviews and the ids of past proposals that cited it. Use after search_evidence
        when a short passage is not enough to write a specific, true claim."""
        try:
            return svc.get_case_study(id, portfolio_id)
        except NotFound as exc:
            raise ToolError(f"not_found: {exc}") from exc

    @mcp.tool(title="List skills", annotations=READ_ONLY)
    def list_skills(portfolio_id: PortfolioIdParam = None) -> SkillList:
        """List every skill the portfolio demonstrates with the number of projects behind it,
        most-evidenced first. Use to check whether a required skill is covered at all before
        searching for evidence."""
        try:
            return svc.list_skills(portfolio_id)
        except NotFound as exc:
            raise ToolError(f"not_found: {exc}") from exc
