"""Prompt templates a freelancer would actually pick from the host's prompt menu."""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .service import PortfolioService

GROUNDING = (
    "Use ONLY the evidence below. Every claim about my experience must be supported by an evidence "
    "id, which you cite in square brackets, e.g. [case:churn-model:0]. If the evidence does not "
    "support something, say so plainly instead of inventing it."
)


def _evidence_block(svc: PortfolioService, query: str, k: int = 5) -> str:
    try:
        items = svc.search_evidence(query, k, None, None).items
    except Exception as exc:  # noqa: BLE001 - prompt must still render
        return f"(evidence lookup failed: {exc})"
    if not items:
        return "(no matching evidence found - tell the user the portfolio does not cover this)"
    return "\n\n".join(
        f"[{i.id}] ({i.type}, {i.date or 'undated'}{', ' + i.outcome if i.outcome else ''}) "
        f"{i.title}\n{i.text}"
        for i in items
    )


def register_prompts(mcp: FastMCP, svc: PortfolioService) -> None:
    @mcp.prompt(title="Answer a screening question from my portfolio")
    def screening_answer(question: str, job_title: str = "", max_words: int = 90) -> str:
        """Draft a short, specific, honest answer to a client's screening question."""
        return (
            f"Answer this client screening question in at most {max_words} words, first person, "
            f"no filler opening.\n\nJob: {job_title or 'n/a'}\nQuestion: {question}\n\n"
            f"{GROUNDING}\n\nEVIDENCE\n{_evidence_block(svc, question)}"
        )

    @mcp.prompt(title="Cover letter from evidence")
    def cover_letter_from_evidence(
        job_title: str, job_description: str, tone: str = "direct and warm", max_words: int = 180
    ) -> str:
        """Write a cover letter whose every claim cites portfolio evidence."""
        return (
            f"Write a cover letter of at most {max_words} words for the job below. Tone: {tone}. "
            "Open with the client's problem, not with 'I'. Lead with the single strongest matching "
            "project, name one concrete result, end with one specific question.\n\n"
            f"{GROUNDING}\n\nJOB: {job_title}\n{job_description}\n\n"
            f"EVIDENCE\n{_evidence_block(svc, f'{job_title} {job_description}'[:480])}"
        )

    @mcp.prompt(title="Check my coverage of a job")
    def portfolio_gap_check(job_description: str) -> str:
        """List which requirements of a job my portfolio proves and which it does not."""
        return (
            "Split the job into atomic requirements. For each, say SUPPORTED / PARTLY / GAP and cite "
            f"evidence ids. {GROUNDING}\n\nJOB\n{job_description}\n\n"
            f"EVIDENCE\n{_evidence_block(svc, job_description[:480], k=8)}"
        )
