"""Portfolio service: retriever selection + case-study/skill/proposal lookups (transport-agnostic)."""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import CaseStudy, EvidenceItem, SearchEvidenceResult, SkillCount, SkillList
from .store import LocalKeywordRetriever, NotFound, PortfolioStore, Retriever

log = logging.getLogger("gigbid.portfolio")

RetrieverSource = Retriever | Callable[[str], Retriever] | None


@dataclass
class PortfolioConfig:
    """``backend``: auto (try GigBid RAG, fall back to local) | rag | local."""

    data_dir: str = field(default_factory=lambda: os.getenv("PORTFOLIO_DATA_DIR", "data/personas"))
    default_portfolio_id: str = field(default_factory=lambda: os.getenv("PORTFOLIO_ID", "default"))
    backend: str = field(default_factory=lambda: os.getenv("PORTFOLIO_BACKEND", "auto"))
    rag_variant: str = field(default_factory=lambda: os.getenv("RAG_VARIANT", "v3_rerank"))


class PortfolioService:
    def __init__(self, config: PortfolioConfig | None = None, retriever: RetrieverSource = None):
        self.config = config or PortfolioConfig()
        self._injected = retriever
        self._cache: dict[str, Retriever] = {}

    def pid(self, portfolio_id: str | None) -> str:
        return portfolio_id or self.config.default_portfolio_id

    def store(self, portfolio_id: str | None) -> PortfolioStore:
        return PortfolioStore(Path(self.config.data_dir), self.pid(portfolio_id))

    def retriever(self, portfolio_id: str | None) -> Retriever:
        pid = self.pid(portfolio_id)
        if pid in self._cache:
            return self._cache[pid]
        r = self._make_retriever(pid)
        self._cache[pid] = r
        return r

    def _make_retriever(self, pid: str) -> Retriever:
        inj = self._injected
        if inj is not None:
            return inj if hasattr(inj, "search") else inj(pid)  # type: ignore[operator]
        if self.config.backend in ("auto", "rag"):
            try:
                from rag.retriever import get_retriever  # type: ignore[import-not-found]

                return get_retriever(self.config.rag_variant, pid)
            except Exception as exc:  # noqa: BLE001 - rag package absent or index not built
                if self.config.backend == "rag":
                    raise
                log.warning("RAG backend unavailable (%s); using local keyword retriever", exc)
        store = self.store(pid)
        if not store.exists():
            raise NotFound(f"portfolio {pid!r} not found under {self.config.data_dir!r}")
        return LocalKeywordRetriever(store)

    # ---- tool bodies ----
    def search_evidence(
        self, requirement: str, k: int, filters: dict | None, portfolio_id: str | None
    ) -> SearchEvidenceResult:
        r = self.retriever(portfolio_id)
        raw = r.search(requirement, k=k, filters=filters or None)
        items = [coerce_item(x) for x in raw[:k]]
        name = getattr(r, "name", type(r).__name__)
        return SearchEvidenceResult(items=items, portfolio_id=self.pid(portfolio_id), retriever=name)

    def get_case_study(self, case_id: str, portfolio_id: str | None) -> CaseStudy:
        store = self.store(portfolio_id)
        text = store.case_study_text(case_id)
        proj = store.project(case_id) or {}
        title = text.splitlines()[0].lstrip("# ").strip() if text else case_id
        return CaseStudy(
            id=case_id,
            project_id=case_id,
            title=proj.get("title") or title,
            markdown=text,
            skills=proj.get("skills", []),
            industry=proj.get("industry"),
            date=proj.get("date"),
            outcome_summary=proj.get("outcome_summary"),
            reviews=[r for r in store.reviews() if r.get("project_id") == case_id],
            related_proposal_ids=[
                p["proposal_id"] for p in store.proposals() if case_id in p.get("project_ids", [])
            ][:20],
        )

    def list_skills(self, portfolio_id: str | None) -> SkillList:
        counts = self.store(portfolio_id).skill_counts()
        skills = [SkillCount(name=n, count=c) for n, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
        return SkillList(skills=skills, portfolio_id=self.pid(portfolio_id))


def coerce_item(raw: Any) -> EvidenceItem:
    """Accept EvidenceRef-like dicts or objects from any retriever variant."""
    d = raw if isinstance(raw, dict) else getattr(raw, "model_dump", lambda: dict(vars(raw)))()
    return EvidenceItem(
        id=str(d.get("id") or d.get("chunk_id") or ""),
        project_id=d.get("project_id"),
        type=str(d.get("type") or "case_study"),
        source=str(d.get("source") or ""),
        title=str(d.get("title") or ""),
        text=str(d.get("text") or d.get("content") or ""),
        date=str(d["date"]) if d.get("date") else None,
        outcome=d.get("outcome"),
        skills=list(d.get("skills") or []),
        score=float(d.get("score") or 0.0),
    )
