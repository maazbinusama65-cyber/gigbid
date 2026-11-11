"""Resource templates so a host can attach full portfolio items to a conversation."""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .service import PortfolioService


def register_resources(mcp: FastMCP, svc: PortfolioService) -> None:
    @mcp.resource("portfolio://case/{id}", name="case_study", mime_type="text/markdown",
                  description="Full markdown of one case study (id = project id).")
    def case_resource(id: str) -> str:
        return svc.get_case_study(id, None).markdown

    @mcp.resource("portfolio://proposal/{id}", name="past_proposal", mime_type="application/json",
                  description="A past proposal with its outcome (won, replied or ignored).")
    def proposal_resource(id: str) -> str:
        return json.dumps(svc.store(None).proposal(id), indent=2, ensure_ascii=False)

    @mcp.resource("portfolio://skills", name="skills", mime_type="application/json",
                  description="Skills the portfolio demonstrates, with project counts.")
    def skills_resource() -> str:
        return svc.list_skills(None).model_dump_json(indent=2)
