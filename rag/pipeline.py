"""Composable retrieval pipeline. Every variant V0-V9 is a `PipelineSpec` over these stages:

    plan queries (whole | decompose | hyde)
      -> per query: candidates (dense | hybrid RRF) over a chunk view -> optional cross-encoder
      -> merge queries by reciprocal-rank fusion
      -> optional skill-graph fusion (V9) -> optional outcome-aware boost (V4)
      -> project-diverse top-k

`scheme` selects the chunk view: fixed (V0), struct, ctx (V6 contextual), mv (V5 multi-vector,
one result per project). `corrective` (V8) swaps the middle for the LangGraph loop in
`rag/corrective.py`. Components toggle independently so the ablation can switch one at a time.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from rag.embedder import Embedder
from rag.index.skillgraph import SkillGraph
from rag.index.store import PersonaIndex, View
from rag.query import HydeFn, extract_requirements, job_text, single_requirement_job, template_hyde
from rag.rerank import Reranker, get_reranker
from rag.types import RESULT_KEYS

DEFAULT_CFG: dict[str, Any] = {
    "n_candidates": 30,       # candidates per query before fusion/rerank
    "rrf_k": 60,
    "rerank_top": 15,         # candidates (per query) sent to the cross-encoder
    "max_per_project": 2,     # evidence items per project in search()/search_job() output
    "outcome": {"won": 1.0, "replied": 0.5, "ignored": -0.3, "proposal_mult": 0.25,
                "project_bonus": 0.35},
    "graph": {"outcome_weight": 0.2, "alpha": 0.6, "top_projects": 6, "weight": 1.0},
    # thresholds tuned on every 5th dev job by `python -m evals.runners.rag_calibrate`
    "corrective": {"strong": 0.80, "weak": 0.72, "min_coverage": 0.34, "max_rewrites": 2},
}
MV_GROUPS = {"summary": ("summary",), "narrative": ("case_study", "cv"), "readme": ("readme",),
             "code": ("code",), "evidence": ("review", "proposal")}
Ranked = list[tuple[int, float]]


@dataclass(frozen=True)
class PipelineSpec:
    scheme: str = "struct"       # fixed | struct | ctx | mv
    query: str = "whole"         # whole | decompose | hyde
    retrieval: str = "dense"     # dense | hybrid
    rerank: bool = False
    outcome: bool = False
    corrective: bool = False
    graph: bool = False

    def components(self) -> dict[str, Any]:
        return {"scheme": self.scheme, "query": self.query, "retrieval": self.retrieval,
                "rerank": self.rerank, "outcome": self.outcome, "corrective": self.corrective,
                "graph": self.graph}

    def label(self) -> str:
        parts = [self.scheme, self.query, self.retrieval]
        parts += [n for n in ("rerank", "outcome", "corrective", "graph") if getattr(self, n)]
        return "+".join(parts)

    def with_(self, **kw) -> PipelineSpec:
        return replace(self, **kw)


def rrf(lists: list[Ranked], k: int = 60, weights: list[float] | None = None) -> Ranked:
    """Reciprocal rank fusion over ranked (row, score) lists -> ranked (row, fused score)."""
    acc: dict[int, float] = {}
    for li, lst in enumerate(lists):
        w = weights[li] if weights else 1.0
        for rank, (row, _) in enumerate(lst):
            acc[row] = acc.get(row, 0.0) + w / (k + rank + 1)
    return sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))


def _deep_merge(base: dict, over: dict | None) -> dict:
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()}
    for k, v in (over or {}).items():
        out[k] = {**out[k], **v} if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Pipeline:
    """A configured retriever. Implements `search` / `search_job` (INTERFACES section 4)."""

    def __init__(self, index: PersonaIndex, spec: PipelineSpec, *, name: str | None = None,
                 embedder: Embedder | None = None, reranker: Reranker | None = None,
                 cfg: dict | None = None, hyde_fn: HydeFn | None = None):
        self.index, self.spec = index, spec
        self.variant = name or spec.label()
        self.embedder = embedder or index.embedder
        self._reranker = reranker
        self.cfg = _deep_merge(DEFAULT_CFG, cfg)
        self.hyde_fn = hyde_fn or template_hyde
        self._graph: SkillGraph | None = None
        self._graph_version = -1
        self._type_masks: dict[tuple, np.ndarray] = {}
        self.last_trace: dict[str, Any] = {}

    # ------------------------------------------------------------------ public API
    @property
    def reranker(self) -> Reranker:
        if self._reranker is None:
            self._reranker = get_reranker()
        return self._reranker

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        """Evidence for ONE requirement (the Fit Matcher / Portfolio MCP call)."""
        return self.search_job(single_requirement_job(requirement), k=k, filters=filters)

    def search_job(self, job: dict, k: int = 5, filters: dict | None = None, *,
                   max_per_project: int | None = -1) -> list[dict]:
        """Evidence for a whole job spec/job dict. ``max_per_project=None`` disables diversity."""
        return self.search_job_detailed(job, k, filters, max_per_project=max_per_project)["items"]

    def search_job_detailed(self, job: dict, k: int = 5, filters: dict | None = None, *,
                            max_per_project: int | None = -1) -> dict[str, Any]:
        """Like search_job but also returns the trace (grades, refusal, uncovered requirements)."""
        if max_per_project == -1:
            max_per_project = self.cfg["max_per_project"]
        t0 = time.perf_counter()
        view = self.index.view(self.spec.scheme)
        ranked, trace = self._run(job, view, view.mask(filters))
        items = self._finalise(view, ranked, k, max_per_project)
        trace.update(variant=self.variant, latency_ms=(time.perf_counter() - t0) * 1000)
        self.last_trace = trace
        return {"items": items, "refused": bool(trace.get("refused")),
                "uncovered": trace.get("uncovered", []), "trace": trace}

    # ------------------------------------------------------------------ orchestration
    def _run(self, job: dict, view: View, mask: np.ndarray | None) -> tuple[Ranked, dict]:
        if not len(view):
            return [], {"queries": []}
        if self.spec.corrective:
            from rag.corrective import run_corrective

            return run_corrective(self, job, view, mask)
        queries = self.plan(job)
        lists = [self.rank_query(view, q, mask) for q in queries]
        merged = rrf(lists, self.cfg["rrf_k"]) if len(lists) > 1 else lists[0]
        if self.spec.graph:
            merged = self._fuse_graph(view, queries, merged)
        if self.spec.outcome:
            merged = self._apply_outcome(view, merged)
        return merged, {"queries": queries}

    def plan(self, job: dict) -> list[str]:
        mode = self.spec.query
        if mode == "decompose":
            return extract_requirements(job) or [job_text(job)]
        if mode == "hyde":
            return [self.hyde_fn(job)]
        return [job_text(job)]

    # ------------------------------------------------------------------ retrieval stages
    def rank_query(self, view: View, query: str, mask: np.ndarray | None) -> Ranked:
        """Candidates for one query: dense|hybrid, then optional rerank (mv: per-view fusion)."""
        if self.spec.scheme == "mv":
            return self._rank_multivector(view, query, mask)
        ranked = self._candidates(view, query, mask)
        return self._rerank(view, query, ranked) if self.spec.rerank else ranked

    def _candidates(self, view: View, query: str, mask: np.ndarray | None) -> Ranked:
        n = self.cfg["n_candidates"]
        qvec = self.embedder.encode([query], is_query=True)[0]
        if self.spec.retrieval == "dense":
            return view.dense(qvec, n, mask)
        dense = view.dense(qvec, 2 * n, mask)
        lex = view.lexical(query, 2 * n, mask)
        return rrf([dense, lex], self.cfg["rrf_k"])[:n]

    def _rerank(self, view: View, query: str, ranked: Ranked) -> Ranked:
        if not ranked:
            return ranked
        ranked = ranked[: self.cfg["rerank_top"]]
        passages = [self._passage(view, r) for r, _ in ranked]
        scores = self.reranker.score(query, passages)
        order = sorted(zip(ranked, scores, strict=True), key=lambda x: -x[1])
        return [(row, float(s)) for (row, _), s in order]

    @staticmethod
    def _passage(view: View, row: int) -> str:
        rec = view.records[row]
        text = rec["text"]
        if view.name == "ctx":
            text = rec["ctx"] + "\n" + text
        return text[:1800]

    def _type_mask(self, view: View, types: tuple[str, ...]) -> np.ndarray:
        key = (view.name, id(view), types)
        if key not in self._type_masks:
            self._type_masks[key] = np.array([r["type"] in types for r in view.records])
        return self._type_masks[key]

    def _rank_multivector(self, view: View, query: str, mask: np.ndarray | None) -> Ranked:
        """V5: rank summary/README/code/narrative/evidence chunks separately, fuse per project."""
        proj_score: dict[str, float] = {}
        best_row: dict[str, tuple[float, int]] = {}
        k = self.cfg["rrf_k"]
        for types in MV_GROUPS.values():
            gmask = self._type_mask(view, types)
            if mask is not None:
                gmask = gmask & mask
            if not gmask.any():
                continue
            ranked = self._candidates(view, query, gmask)
            if self.spec.rerank:
                ranked = self._rerank(view, query, ranked)
            seen: set[str] = set()
            for row, _ in ranked:
                rec = view.records[row]
                pid = rec["project_id"] or rec["id"]
                if pid in seen:
                    continue
                seen.add(pid)
                gain = 1.0 / (k + len(seen))
                proj_score[pid] = proj_score.get(pid, 0.0) + gain
                if pid not in best_row or gain > best_row[pid][0]:
                    best_row[pid] = (gain, row)
        ordered = sorted(proj_score.items(), key=lambda kv: -kv[1])
        return [(best_row[pid][1], s) for pid, s in ordered]

    # ------------------------------------------------------------------ V9 / V4
    def get_graph(self) -> SkillGraph:
        if self._graph is None or self._graph_version != self.index.version:
            g = self.cfg["graph"]
            self._graph = SkillGraph(self.index.view("mv").records,
                                     outcome_weight=g["outcome_weight"], alpha=g["alpha"])
            self._graph_version = self.index.version
        return self._graph

    def _fuse_graph(self, view: View, queries: list[str], merged: Ranked) -> Ranked:
        graph = self.get_graph()
        pscore: dict[str, float] = {}
        for q in queries:
            scores = graph.score_projects(q)
            top = max(scores.values(), default=0.0)
            for pid, s in scores.items():
                pscore[pid] = pscore.get(pid, 0.0) + (s / top if top else 0.0)
        if not pscore:
            return merged
        base = dict(merged)
        top_p = sorted(pscore, key=lambda p: -pscore[p])[: self.cfg["graph"]["top_projects"]]
        rows = [(i, r["project_id"]) for i, r in enumerate(view.records)
                if r["project_id"] in top_p]
        rows.sort(key=lambda ir: (-pscore[ir[1]], -base.get(ir[0], 0.0), ir[0]))
        graph_list = [(i, pscore[p]) for i, p in rows][: 3 * self.cfg["n_candidates"]]
        return rrf([merged, graph_list], self.cfg["rrf_k"],
                   [1.0, self.cfg["graph"]["weight"]])

    def _apply_outcome(self, view: View, ranked: Ranked) -> Ranked:
        """V4: boost proposals that won/replied and the projects they cite as evidence."""
        if not ranked:
            return ranked
        oc = self.cfg["outcome"]
        scores = np.array([s for _, s in ranked], dtype=float)
        span = scores.max() - scores.min()
        norm = (scores - scores.min()) / span if span > 0 else np.ones_like(scores)
        bonus: dict[str, float] = {}
        for (row, _), n in zip(ranked, norm, strict=True):
            rec = view.records[row]
            if rec["type"] == "proposal" and rec["outcome"] in oc:
                for pid in rec["project_ids"]:
                    bonus[pid] = bonus.get(pid, 0.0) + n * oc[rec["outcome"]]
        out = []
        for (row, _), n in zip(ranked, norm, strict=True):
            rec = view.records[row]
            val = float(n)
            if rec["type"] == "proposal" and rec["outcome"] in oc:
                val *= 1.0 + oc["proposal_mult"] * oc[rec["outcome"]]
            pids = rec["project_ids"] or ([rec["project_id"]] if rec["project_id"] else [])
            val += oc["project_bonus"] * max((bonus.get(p, 0.0) for p in pids), default=0.0) * 0.5
            out.append((row, val))
        return sorted(out, key=lambda x: (-x[1], x[0]))

    # ------------------------------------------------------------------ output
    def _finalise(self, view: View, ranked: Ranked, k: int, max_per_project: int | None
                  ) -> list[dict]:
        out: list[dict] = []
        per_project: dict[str, int] = {}
        for row, score in ranked:
            rec = view.records[row]
            pid = rec["project_id"]
            if max_per_project is not None and pid:
                if per_project.get(pid, 0) >= max_per_project:
                    continue
                per_project[pid] = per_project.get(pid, 0) + 1
            out.append(self._item(rec, score))
            if len(out) >= k:
                break
        return out

    @staticmethod
    def _item(rec: dict, score: float) -> dict:
        item = {key: rec.get(key) for key in RESULT_KEYS}
        item["skills"] = list(rec["skills"])
        item["score"] = float(score)
        item["client_industry"] = rec.get("client_industry")
        item["project_ids"] = list(rec.get("project_ids") or [])
        return item
