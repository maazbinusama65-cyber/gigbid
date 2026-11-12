"""V8 corrective / self-RAG loop as a small LangGraph StateGraph.

    plan -> retrieve -> grade -> (weak/none and attempts left?) -> rewrite -> retrieve ...
                                 \\-> finish (merge covered requirements, or REFUSE)

Grading is deterministic: a requirement is *strong* when the best of its top-3 candidates has
cosine >= `strong`, *weak* when >= `weak`, else *none* (embedder cosine, same model as retrieval).
Weak/none requirements are re-queried with an expanded query (job skills + category, then a
hypothetical-evidence rewrite). After `max_rewrites` rounds, requirements still graded none are
reported in `trace["uncovered"]` and get no evidence ("refuse to claim"). If fewer than
`min_coverage` of requirements are covered the whole job is refused (empty result list).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

import numpy as np
from langgraph.graph import END, StateGraph

from rag.index.store import View
from rag.query import extract_requirements, job_text, template_hyde

if TYPE_CHECKING:  # pragma: no cover
    from rag.pipeline import Pipeline, Ranked


class CState(TypedDict, total=False):
    job: dict
    view: Any
    mask: Any
    reqs: list[str]
    queries: dict[str, str]
    ranked: dict[str, list]
    support: dict[str, float]
    grade: dict[str, str]
    pending: list[str]
    attempt: int
    refused: bool
    log: list[str]


def _grade(support: float, cfg: dict) -> str:
    if support >= cfg["strong"]:
        return "strong"
    return "weak" if support >= cfg["weak"] else "none"


def _support(pipe: Pipeline, view: View, requirement: str, ranked: list) -> float:
    """Best cosine between the *original* requirement and its top-3 candidates."""
    if not ranked:
        return 0.0
    q = pipe.embedder.encode([requirement], is_query=True)[0]
    rows = [r for r, _ in ranked[:3]]
    return float(np.max(view.emb[rows] @ q))


def build_graph(pipe: Pipeline):
    cfg = pipe.cfg["corrective"]

    def plan(state: CState) -> CState:
        job = state["job"]
        if pipe.spec.query == "whole":
            reqs = [job_text(job)]
        else:
            reqs = extract_requirements(job) or [job_text(job)]
        return {"reqs": reqs, "queries": {r: r for r in reqs}, "ranked": {}, "support": {},
                "grade": {}, "pending": list(reqs), "attempt": 0, "log": ["plan"]}

    def retrieve(state: CState) -> CState:
        ranked, support = dict(state["ranked"]), dict(state["support"])
        for req in state["pending"]:
            lst = pipe.rank_query(state["view"], state["queries"][req], state["mask"])
            new_support = _support(pipe, state["view"], req, lst)
            if req not in ranked or new_support >= support.get(req, -1.0):
                ranked[req], support[req] = lst, new_support
        return {"ranked": ranked, "support": support, "log": state["log"] + ["retrieve"]}

    def grade(state: CState) -> CState:
        grades = {r: _grade(state["support"][r], cfg) for r in state["reqs"]}
        pending = [r for r, g in grades.items() if g != "strong"]
        return {"grade": grades, "pending": pending, "log": state["log"] + ["grade"]}

    def route(state: CState) -> str:
        if state["pending"] and state["attempt"] < cfg["max_rewrites"]:
            return "rewrite"
        return "finish"

    def rewrite(state: CState) -> CState:
        job, attempt = state["job"], state["attempt"] + 1
        skills = ", ".join(job.get("required_skills", [])[:6])
        queries = dict(state["queries"])
        for req in state["pending"]:
            if attempt == 1:
                queries[req] = f"{req}. {job.get('category', '')} {skills}".strip()
            else:
                hyp = {"title": req, "description": req, "requirements": [req],
                       "required_skills": job.get("required_skills", [])}
                queries[req] = template_hyde(hyp)
        return {"queries": queries, "attempt": attempt, "log": state["log"] + [f"rewrite{attempt}"]}

    def finish(state: CState) -> CState:
        covered = [r for r in state["reqs"] if state["grade"][r] != "none"]
        refused = len(covered) / max(len(state["reqs"]), 1) < cfg["min_coverage"]
        return {"refused": refused, "log": state["log"] + ["finish"]}

    g = StateGraph(CState)
    for name, fn in (("plan", plan), ("retrieve", retrieve), ("grade", grade),
                     ("rewrite", rewrite), ("finish", finish)):
        g.add_node(name, fn)
    g.set_entry_point("plan")
    g.add_edge("plan", "retrieve")
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", route, {"rewrite": "rewrite", "finish": "finish"})
    g.add_edge("rewrite", "retrieve")
    g.add_edge("finish", END)
    return g.compile()


def run_corrective(pipe: Pipeline, job: dict, view: View, mask) -> tuple[Ranked, dict]:
    graph = getattr(pipe, "_corrective_graph", None)
    if graph is None:
        graph = pipe._corrective_graph = build_graph(pipe)  # type: ignore[attr-defined]
    final = graph.invoke({"job": job, "view": view, "mask": mask})
    reqs, grades = final["reqs"], final["grade"]
    uncovered = [r for r in reqs if grades[r] == "none"]
    trace = {"queries": list(final["queries"].values()), "grades": grades,
             "support": final["support"], "uncovered": uncovered, "refused": final["refused"],
             "rewrites": final["attempt"], "path": final["log"]}
    if final["refused"]:
        return [], trace
    from rag.pipeline import rrf

    lists = [final["ranked"][r] for r in reqs if grades[r] != "none"]
    merged = rrf(lists, pipe.cfg["rrf_k"]) if len(lists) > 1 else lists[0]
    if pipe.spec.graph:
        merged = pipe._fuse_graph(view, [final["queries"][r] for r in reqs], merged)
    if pipe.spec.outcome:
        merged = pipe._apply_outcome(view, merged)
    return merged, trace
