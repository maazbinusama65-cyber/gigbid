"""V9 skill graph (GraphRAG-lite): skills, projects, client industries and outcomes as a graph.

Nodes: ("skill", name), ("project", id), ("industry", name), ("outcome", won|replied|ignored).
Edges (weighted): project-skill (skill named in the project's own documents counts more than a
fact-sheet-only skill), project-industry (the project's client industry plus industries of
reviews/proposals citing it), project-outcome (past proposals citing the project, by outcome).
A query activates skill (and mentioned-industry) seeds; personalised PageRank spreads activation
to projects, so a project reached via a shared neighbouring skill still scores. Also answers
"have I done X for a client in industry Y?" via ``experience``.
"""
from __future__ import annotations

import math
import re

import networkx as nx

from rag.ingest.loaders import SkillVocab
from rag.text import tokenize


def _match(token: str, skill_key: str) -> bool:
    if token == skill_key:
        return True
    return (len(token) >= 5 and skill_key.startswith(token)) or (
        len(skill_key) >= 5 and token.startswith(skill_key))


class SkillGraph:
    def __init__(self, records: list[dict], *, outcome_weight: float = 0.2, alpha: float = 0.6):
        self.alpha = alpha
        g = nx.Graph()
        self.projects: dict[str, dict] = {}
        skills: set[str] = set()
        for r in records:
            if r["project_id"] and r["type"] != "proposal":
                skills.update(r["skills"])
        self.vocab = SkillVocab(skills)
        text_hits: dict[tuple[str, str], int] = {}
        for r in records:
            pids = [p for p in (r.get("project_ids") or [r["project_id"]]) if p]
            for pid in pids:
                meta = self.projects.setdefault(pid, {"title": r["project_title"], "skills": set(),
                                                      "industries": set(), "won": 0, "replied": 0,
                                                      "ignored": 0, "_docs": set()})
                meta["title"] = meta["title"] or r["project_title"]
                if r["type"] == "proposal":
                    if r["doc_id"] not in meta["_docs"]:
                        meta["_docs"].add(r["doc_id"])
                        if r["outcome"] in ("won", "replied", "ignored"):
                            meta[r["outcome"]] += 1
                    if r["client_industry"]:
                        meta["industries"].add(r["client_industry"])
                    continue
                meta["skills"].update(r["skills"])
                if r["client_industry"]:
                    meta["industries"].add(r["client_industry"])
                for s in self.vocab.find(r["text"]):
                    text_hits[(pid, s)] = text_hits.get((pid, s), 0) + 1
        for pid, meta in self.projects.items():
            for s in meta["skills"]:
                w = 1.0 + math.log1p(text_hits.get((pid, s), 0))
                g.add_edge(("project", pid), ("skill", s), weight=w)
            for ind in meta["industries"]:
                g.add_edge(("project", pid), ("industry", ind.lower()), weight=1.0)
            for outcome in ("won", "replied", "ignored"):
                if meta[outcome]:
                    wt = outcome_weight * meta[outcome] * {"won": 1.0, "replied": 0.6,
                                                           "ignored": 0.1}[outcome]
                    g.add_edge(("project", pid), ("outcome", outcome), weight=wt)
        self.g = g
        n_proj = max(len(self.projects), 1)
        self.idf = {}
        for node in g:
            if node[0] == "skill":
                df = sum(1 for _ in g.neighbors(node))
                self.idf[node[1]] = math.log(1 + n_proj / max(df, 1))

    # ------------------------------------------------------------------ query side
    def query_seeds(self, text: str) -> dict[tuple[str, str], float]:
        tokens = set(tokenize(text, drop_stop=False))
        seeds: dict[tuple[str, str], float] = {}
        for node in self.g:
            kind, name = node
            if kind == "skill":
                key = name.lower()
                if key in tokens or any(_match(t, key) for t in tokens if len(t) >= 5) or (
                        " " in key and re.search(re.escape(key), text, re.IGNORECASE)):
                    seeds[node] = self.idf.get(name, 1.0)
            elif kind == "industry" and name in tokens:
                seeds[node] = 1.0
        return seeds

    def score_projects(self, text: str) -> dict[str, float]:
        seeds = self.query_seeds(text)
        if not seeds:
            return {}
        total = sum(seeds.values())
        pers = {n: seeds.get(n, 0.0) / total for n in self.g}
        pr = nx.pagerank(self.g, alpha=self.alpha, personalization=pers, weight="weight",
                         max_iter=60, tol=1e-6)
        return {n[1]: s for n, s in pr.items() if n[0] == "project"}

    # ------------------------------------------------------------------ "have I done X for Y?"
    def experience(self, skill: str, industry: str | None = None) -> list[dict]:
        """Projects using `skill` (optionally for clients in `industry`), best first."""
        out = []
        key = skill.lower()
        for pid, meta in self.projects.items():
            if not any(_match(key, s.lower()) or _match(s.lower(), key) for s in meta["skills"]):
                continue
            inds = {i.lower() for i in meta["industries"]}
            if industry and industry.lower() not in inds:
                continue
            out.append({"project_id": pid, "title": meta["title"],
                        "industries": sorted(meta["industries"]), "won": meta["won"],
                        "replied": meta["replied"]})
        return sorted(out, key=lambda r: (-r["won"], -r["replied"], r["project_id"]))
