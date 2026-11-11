"""File-backed portfolio store + a dependency-free keyword (BM25) retriever.

Layout (the same one ``gigsim.datagen`` writes, see docs/INTERFACES.md section 1)::

    <data_dir>/<portfolio_id>/
        profile.json  cv.md  projects.json  reviews.json  proposals.json
        case_studies/<project_id>.md
        repos/<project_id>/README.md

Any freelancer can point ``PORTFOLIO_DATA_DIR`` at a folder with this shape and use the server
without the GigBid RAG stack.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Protocol

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")
_STOP = frozenset(
    "a an the and or of to in on for with by is are was were be as at from that this it its our we "
    "you your i my me have has had not but if then than so such can will would should could".split()
)


class NotFound(LookupError):
    pass


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


class Retriever(Protocol):
    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]: ...


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _chunks(text: str, max_chars: int = 700) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) > max_chars:
            out.append(buf)
            buf = p
        else:
            buf = f"{buf}\n\n{p}".strip()
    if buf:
        out.append(buf)
    return out


class PortfolioStore:
    """Read-only access to one portfolio directory. ``portfolio_id`` must be a safe slug."""

    def __init__(self, data_dir: str | Path, portfolio_id: str) -> None:
        if not re.fullmatch(r"[a-z0-9_\-]{1,40}", portfolio_id):
            raise ValueError("invalid portfolio_id")
        self.portfolio_id = portfolio_id
        self.root = Path(data_dir) / portfolio_id

    def exists(self) -> bool:
        return self.root.is_dir()

    @staticmethod
    def _check_id(item_id: str) -> str:
        if not _ID_RE.fullmatch(item_id):
            raise NotFound(f"invalid id {item_id!r}")
        return item_id

    def projects(self) -> list[dict]:
        return _read_json(self.root / "projects.json", [])

    def project(self, project_id: str) -> dict | None:
        return next((p for p in self.projects() if p.get("project_id") == project_id), None)

    def proposals(self) -> list[dict]:
        return _read_json(self.root / "proposals.json", [])

    def reviews(self) -> list[dict]:
        return _read_json(self.root / "reviews.json", [])

    def case_study_text(self, project_id: str) -> str:
        self._check_id(project_id)
        path = self.root / "case_studies" / f"{project_id}.md"
        if not path.is_file():
            raise NotFound(f"case study {project_id!r} not found in portfolio {self.portfolio_id!r}")
        return path.read_text(encoding="utf-8")

    def proposal(self, proposal_id: str) -> dict:
        self._check_id(proposal_id)
        for p in self.proposals():
            if p.get("proposal_id") == proposal_id:
                return p
        raise NotFound(f"proposal {proposal_id!r} not found in portfolio {self.portfolio_id!r}")

    def skill_counts(self) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for p in self.projects():
            counts.update({s for s in p.get("skills", [])})
        if not counts:
            profile = _read_json(self.root / "profile.json", {})
            counts.update({s: 1 for s in profile.get("skills", [])})
        return dict(counts)


class LocalKeywordRetriever:
    """BM25 over case-study, README, review, proposal and CV chunks. Deterministic, offline."""

    name = "local-bm25"

    def __init__(self, store: PortfolioStore) -> None:
        self._docs = self._build(store)
        self._df: Counter[str] = Counter()
        for d in self._docs:
            self._df.update(set(d["_tokens"]))
        n = max(1, len(self._docs))
        self._avg = sum(len(d["_tokens"]) for d in self._docs) / n

    @staticmethod
    def _build(store: PortfolioStore) -> list[dict]:
        docs: list[dict] = []
        projects = {p["project_id"]: p for p in store.projects() if "project_id" in p}

        def add(id_: str, type_: str, source: str, text: str, **kw: Any) -> None:
            pid = kw.get("project_id")
            proj = projects.get(pid or "", {})
            doc = {
                "id": id_, "type": type_, "source": source, "text": text,
                "title": kw.get("title") or proj.get("title", ""),
                "project_id": pid, "date": kw.get("date") or proj.get("date"),
                "outcome": kw.get("outcome"), "skills": kw.get("skills") or proj.get("skills", []),
            }
            doc["_tokens"] = tokenize(f"{doc['title']} {text} {' '.join(doc['skills'])}")
            docs.append(doc)

        cs_dir = store.root / "case_studies"
        if cs_dir.is_dir():
            for f in sorted(cs_dir.glob("*.md")):
                text = f.read_text(encoding="utf-8")
                title = text.splitlines()[0].lstrip("# ").strip() if text else f.stem
                for i, ch in enumerate(_chunks(text)):
                    add(f"case:{f.stem}:{i}", "case_study", f"case_studies/{f.name}", ch,
                        project_id=f.stem, title=title)
        repos = store.root / "repos"
        if repos.is_dir():
            for f in sorted(repos.glob("*/README.md")):
                for i, ch in enumerate(_chunks(f.read_text(encoding="utf-8"))):
                    add(f"readme:{f.parent.name}:{i}", "readme", f"repos/{f.parent.name}/README.md",
                        ch, project_id=f.parent.name)
        for r in store.reviews():
            add(f"review:{r.get('review_id')}", "review", "reviews.json", r.get("text", ""),
                project_id=r.get("project_id"), date=r.get("date"))
        for p in store.proposals():
            add(f"proposal:{p.get('proposal_id')}", "proposal", "proposals.json", p.get("text", ""),
                title=p.get("job_title", ""), date=p.get("date"), outcome=p.get("outcome"),
                project_id=(p.get("project_ids") or [None])[0])
        cv = store.root / "cv.md"
        if cv.is_file():
            for i, ch in enumerate(_chunks(cv.read_text(encoding="utf-8"))):
                add(f"cv:{i}", "cv", "cv.md", ch, title="CV")
        return docs

    @staticmethod
    def _passes(doc: dict, f: dict) -> bool:
        if f.get("types") and doc["type"] not in f["types"]:
            return False
        if f.get("project_id") and doc["project_id"] != f["project_id"]:
            return False
        if f.get("outcome") and doc["outcome"] != f["outcome"]:
            return False
        if f.get("since") and not (doc["date"] and str(doc["date"]) >= f["since"]):
            return False
        if f.get("skills"):
            hay = " ".join(doc["skills"]).lower() + " " + doc["text"].lower()
            if not any(s.lower() in hay for s in f["skills"]):
                return False
        return True

    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]:
        q = tokenize(requirement)
        n = len(self._docs)
        scored: list[tuple[float, dict]] = []
        for d in self._docs:
            if filters and not self._passes(d, filters):
                continue
            tf = Counter(d["_tokens"])
            dl = len(d["_tokens"]) or 1
            s = 0.0
            for t in set(q):
                if t not in tf:
                    continue
                idf = math.log(1 + (n - self._df[t] + 0.5) / (self._df[t] + 0.5))
                s += idf * tf[t] * 2.5 / (tf[t] + 1.5 * (0.25 + 0.75 * dl / (self._avg or 1)))
            if s > 0:
                scored.append((s, d))
        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        top = scored[0][0] if scored else 1.0
        return [
            {**{k_: v for k_, v in d.items() if not k_.startswith("_")}, "score": round(s / top, 4)}
            for s, d in scored[:k]
        ]
