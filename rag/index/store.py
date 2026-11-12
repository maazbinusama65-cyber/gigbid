"""Persistent per-persona index: chunk records + embeddings + BM25, with incremental updates.

Why a tiny numpy index behind an interface instead of Chroma/Qdrant?  A persona has well under
10k chunks, so exact brute-force cosine (one matrix-vector product, <1 ms) beats an ANN index on
recall and removes a service/dependency from the CI, the evals and the Docker image.  All access
goes through ``View.dense`` / ``View.lexical`` / ``PersonaIndex.add_document`` so a Chroma or
Qdrant adapter can replace this file without touching variants.

On-disk layout (``data/processed/index/<persona>/``): ``meta.json`` (embedder, context id, doc
hashes), ``fixed.json`` / ``struct.json`` (chunk metadata), ``emb_*.npy`` (float32 embeddings).

Chunk "kinds": ``fixed`` (V0 blind windows) and ``struct`` (structure-aware). Three embedding
matrices exist: fixed, struct, and ctx (struct chunks embedded with a context line, V6).
Views (what a variant retrieves over): fixed, struct, ctx, mv (struct + per-project summaries).
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from rag.embedder import Embedder
from rag.index.bm25 import BM25Index
from rag.ingest.chunkers import chunk_document
from rag.types import Document

INDEX_VERSION = 3
ContextFn = Callable[[Document, str, int], str]


def template_context(doc: Document, chunk_text: str, idx: int) -> str:
    """Default (offline) context line prepended to each chunk for V6."""
    proj = doc.project_title or doc.title
    skills = ", ".join(doc.skills[:6])
    when = f", {doc.date}" if doc.date else ""
    industry = f" in the {doc.client_industry} industry" if doc.client_industry else ""
    if doc.type == "proposal":
        extra = f" (outcome: {doc.outcome})" if doc.outcome else ""
        return (f"Context: past proposal '{doc.title}'{extra} citing project '{proj}'"
                f"{industry}{when}. Skills: {skills}.")
    if doc.type == "cv":
        return f"Context: the freelancer's CV. Skills: {skills}."
    if doc.type == "review":
        return f"Context: client review of project '{proj}'{industry}{when}. Skills: {skills}."
    label = {"code": f"code file {doc.source}", "readme": "repository README",
             "case_study": "case study", "summary": "project summary"}.get(doc.type, doc.type)
    return f"Context: {label} of project '{proj}'{industry}{when}. Skills: {skills}."


template_context.context_id = "template-v1"  # type: ignore[attr-defined]


def make_filter_mask(records: list[dict], filters: dict | None) -> np.ndarray | None:
    """Metadata filter: scalar equality / list membership; `skills` = any overlap;
    `date_gte` / `date_lte` compare ISO date strings."""
    if not filters:
        return None
    mask = np.ones(len(records), dtype=bool)
    for i, rec in enumerate(records):
        for key, want in filters.items():
            if want is None:
                continue
            if key == "skills":
                wants = {w.lower() for w in ([want] if isinstance(want, str) else want)}
                if not wants & {s.lower() for s in rec["skills"]}:
                    mask[i] = False
            elif key == "date_gte":
                if not rec.get("date") or rec["date"] < want:
                    mask[i] = False
            elif key == "date_lte":
                if not rec.get("date") or rec["date"] > want:
                    mask[i] = False
            elif key == "project_id":
                pids = rec.get("project_ids") or [rec.get("project_id")]
                if want not in pids:
                    mask[i] = False
            else:
                val = rec.get(key)
                ok = val in want if isinstance(want, (list, tuple, set)) else val == want
                if not ok:
                    mask[i] = False
    return mask


class View:
    """A retrievable slice: parallel lists of records, embeddings and a BM25 index."""

    def __init__(self, name: str, records: list[dict], emb: np.ndarray | None,
                 lexical_texts: list[str]):
        self.name = name
        self.records = records
        self.emb = emb if emb is not None else np.zeros((0, 1), dtype=np.float32)
        self._lex_texts = lexical_texts
        self._bm25: BM25Index | None = None

    def __len__(self) -> int:
        return len(self.records)

    @property
    def bm25(self) -> BM25Index:
        if self._bm25 is None:
            self._bm25 = BM25Index(self._lex_texts)
        return self._bm25

    def mask(self, filters: dict | None) -> np.ndarray | None:
        return make_filter_mask(self.records, filters)

    @staticmethod
    def _top(scores: np.ndarray, n: int, mask: np.ndarray | None) -> list[tuple[int, float]]:
        if mask is not None:
            scores = np.where(mask, scores, -np.inf)
        n = min(n, len(scores))
        if n <= 0:
            return []
        idx = np.argpartition(-scores, n - 1)[:n]
        idx = idx[np.argsort(-scores[idx], kind="stable")]
        return [(int(i), float(scores[i])) for i in idx if np.isfinite(scores[i])]

    def dense_scores(self, qvec: np.ndarray) -> np.ndarray:
        if not len(self.records):
            return np.zeros(0, dtype=np.float32)
        return self.emb @ qvec

    def dense(self, qvec: np.ndarray, n: int, mask: np.ndarray | None = None
              ) -> list[tuple[int, float]]:
        return self._top(self.dense_scores(qvec), n, mask)

    def lexical(self, query: str, n: int, mask: np.ndarray | None = None
                ) -> list[tuple[int, float]]:
        scores = self.bm25.scores(query)
        return [(i, s) for i, s in self._top(scores, n, mask) if s > 0]


class PersonaIndex:
    def __init__(self, persona: str, embedder: Embedder, *, context_fn: ContextFn | None = None,
                 root: str | Path | None = None):
        self.persona = persona
        self.embedder = embedder
        self.context_fn = context_fn or template_context
        self.root = Path(root) if root else None
        self.docs: dict[str, dict[str, Any]] = {}  # doc_id -> {"hash": str, "type": str}
        self._recs = {"fixed": [], "struct": []}
        self._emb: dict[str, np.ndarray | None] = {"fixed": None, "struct": None, "ctx": None}
        self._views: dict[str, View] = {}
        self.version = 0  # bumps on every mutation (caches key on it)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _stack(old: np.ndarray | None, new: np.ndarray) -> np.ndarray:
        return new if old is None or not len(old) else np.vstack([old, new])

    @property
    def context_id(self) -> str:
        return getattr(self.context_fn, "context_id", "custom")

    def _rec(self, doc: Document, chunk: dict, n: int, kind: str) -> dict:
        return {"id": f"{doc.doc_id}#{kind[0]}{n}", "doc_id": doc.doc_id, "persona": doc.persona,
                "type": doc.type, "project_id": doc.project_id, "project_ids": doc.project_ids,
                "title": doc.title, "source": doc.source, "heading": chunk["heading"],
                "text": chunk["text"], "date": doc.date, "outcome": doc.outcome,
                "skills": doc.skills, "client_industry": doc.client_industry,
                "project_title": doc.project_title}

    # ------------------------------------------------------------------ mutation
    def add_documents(self, docs: list[Document]) -> dict[str, int]:
        """Add/update documents; unchanged ones (same content+metadata hash) are skipped."""
        stats = {"added": 0, "updated": 0, "unchanged": 0}
        todo: list[Document] = []
        for doc in docs:
            h = doc.content_hash()
            old = self.docs.get(doc.doc_id)
            if old and old["hash"] == h:
                stats["unchanged"] += 1
                continue
            stats["updated" if old else "added"] += 1
            todo.append(doc)
        if not todo:
            return stats
        self._drop({d.doc_id for d in todo})
        new = {"fixed": [], "struct": []}
        ctx_texts: list[str] = []
        for doc in todo:
            if doc.type != "summary":
                for n, ch in enumerate(chunk_document(doc, "fixed")):
                    new["fixed"].append(self._rec(doc, ch, n, "fixed"))
            for n, ch in enumerate(chunk_document(doc, "struct")):
                rec = self._rec(doc, ch, n, "struct")
                rec["ctx"] = self.context_fn(doc, ch["text"], n)
                new["struct"].append(rec)
                ctx_texts.append(rec["ctx"] + "\n" + ch["text"])
            self.docs[doc.doc_id] = {"hash": doc.content_hash(), "type": doc.type}
        if new["fixed"]:
            self._append("fixed", new["fixed"], self.embedder.encode([r["text"] for r in new["fixed"]]))
        if new["struct"]:
            self._append("struct", new["struct"],
                         self.embedder.encode([r["text"] for r in new["struct"]]))
            self._emb["ctx"] = self._stack(self._emb["ctx"], self.embedder.encode(ctx_texts))
        self._views.clear()
        self.version += 1
        return stats

    def add_document(self, doc: Document) -> str:
        """Incremental update for ONE document (UI 'add work'): only this doc is re-embedded."""
        stats = self.add_documents([doc])
        return next(k for k, v in stats.items() if v)

    def remove_document(self, doc_id: str) -> bool:
        if doc_id not in self.docs:
            return False
        self._drop({doc_id})
        self._views.clear()
        self.version += 1
        return True

    def sync(self, docs: list[Document]) -> dict[str, int]:
        """Make the index equal to ``docs``: add new, update changed, remove vanished."""
        stats = self.add_documents(docs)
        keep = {d.doc_id for d in docs}
        gone = [d for d in self.docs if d not in keep]
        for d in gone:
            self.remove_document(d)
        stats["removed"] = len(gone)
        return stats

    def _append(self, kind: str, recs: list[dict], emb: np.ndarray) -> None:
        self._recs[kind].extend(recs)
        self._emb[kind] = self._stack(self._emb[kind], emb)

    def _drop(self, doc_ids: set[str]) -> None:
        for kind in ("fixed", "struct"):
            keep = [i for i, r in enumerate(self._recs[kind]) if r["doc_id"] not in doc_ids]
            if len(keep) == len(self._recs[kind]):
                continue
            self._recs[kind] = [self._recs[kind][i] for i in keep]
            self._emb[kind] = self._emb[kind][keep]  # type: ignore[index]
            if kind == "struct":
                self._emb["ctx"] = self._emb["ctx"][keep]  # type: ignore[index]
        for d in doc_ids:
            self.docs.pop(d, None)

    # ------------------------------------------------------------------ views
    def view(self, name: str) -> View:
        if name in self._views:
            return self._views[name]
        if name == "fixed":
            v = View(name, self._recs["fixed"], self._emb["fixed"],
                     [r["text"] for r in self._recs["fixed"]])
        elif name in ("struct", "ctx", "mv"):
            keep = [i for i, r in enumerate(self._recs["struct"])
                    if name == "mv" or r["type"] != "summary"]
            recs = [self._recs["struct"][i] for i in keep]
            full = self._emb["ctx" if name == "ctx" else "struct"]
            emb = full[keep] if full is not None else None
            if name == "ctx":
                texts = [r["ctx"] + "\n" + r["text"] for r in recs]
            else:
                texts = [r["text"] for r in recs]
            v = View(name, recs, emb, texts)
        else:
            raise ValueError(f"unknown view {name!r}")
        self._views[name] = v
        return v

    def project_meta(self) -> dict[str, dict]:
        """project_id -> {title, skills, industry, date} reconstructed from chunk metadata."""
        out: dict[str, dict] = {}
        for r in self._recs["struct"]:
            pid = r["project_id"]
            if not pid or r["type"] in ("proposal",):
                continue
            m = out.setdefault(pid, {"title": r["project_title"], "skills": [], "industry": None,
                                     "date": None})
            m["title"] = m["title"] or r["project_title"]
            m["skills"] = list(dict.fromkeys(m["skills"] + r["skills"]))
            m["industry"] = m["industry"] or r["client_industry"]
            m["date"] = m["date"] or r["date"]
        return out

    # ------------------------------------------------------------------ persistence
    def _dir(self) -> Path:
        if not self.root:
            raise ValueError("index has no root directory")
        # the offline hash embedder gets its own directory so it can never clobber a real index
        tag = f".{self.embedder.name}" if self.embedder.name.startswith("hash") else ""
        return self.root / f"{self.persona}{tag}"

    def save(self) -> Path:
        d = self._dir()
        d.mkdir(parents=True, exist_ok=True)
        meta = {"version": INDEX_VERSION, "embedder": self.embedder.name,
                "context_id": self.context_id, "docs": self.docs}
        (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        for kind in ("fixed", "struct"):
            (d / f"{kind}.json").write_text(json.dumps(self._recs[kind]), encoding="utf-8")
            if self._emb[kind] is not None:
                np.save(d / f"emb_{kind}.npy", self._emb[kind])
        if self._emb["ctx"] is not None:
            np.save(d / "emb_ctx.npy", self._emb["ctx"])
        return d

    @classmethod
    def load(cls, persona: str, embedder: Embedder, root: str | Path, *,
             context_fn: ContextFn | None = None) -> PersonaIndex:
        """Load a persisted index; returns an empty index if absent or built with other settings."""
        idx = cls(persona, embedder, context_fn=context_fn, root=root)
        d = idx._dir()
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            if (meta["version"] != INDEX_VERSION or meta["embedder"] != embedder.name
                    or meta["context_id"] != idx.context_id):
                return idx
            recs = {k: json.loads((d / f"{k}.json").read_text(encoding="utf-8"))
                    for k in ("fixed", "struct")}
            emb = {k: np.load(d / f"emb_{k}.npy") for k in ("fixed", "struct", "ctx")}
        except (FileNotFoundError, KeyError, ValueError):
            return idx
        if len(recs["fixed"]) != len(emb["fixed"]) or len(recs["struct"]) != len(emb["struct"]) \
                or len(emb["ctx"]) != len(emb["struct"]):
            return idx
        idx.docs, idx._recs, idx._emb = meta["docs"], recs, emb  # type: ignore[assignment]
        return idx

    def wipe(self) -> None:
        if self.root and self._dir().exists():
            shutil.rmtree(self._dir())

    def stats(self) -> dict[str, Any]:
        return {"persona": self.persona, "docs": len(self.docs),
                "fixed_chunks": len(self._recs["fixed"]), "struct_chunks": len(self._recs["struct"]),
                "embedder": self.embedder.name, "doc_types": _count(d["type"] for d in self.docs.values())}


def _count(items) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def doc_to_dict(doc: Document) -> dict:
    return asdict(doc)
