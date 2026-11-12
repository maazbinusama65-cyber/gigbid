"""Retriever factory (INTERFACES section 4).

    get_retriever(variant, portfolio_id) -> Retriever
        .search(requirement, k=5, filters=None) -> list[dict]      # one requirement
        .search_job(job_spec_dict, k=5)         -> list[dict]      # whole job

`variant` defaults to config.yaml `rag.variant` (env RAG_VARIANT overrides) and may be a
composition such as ``"v1_decompose+v2_hybrid+v3_rerank"``. `portfolio_id` defaults to env
PORTFOLIO_ID. Result dicts: {id, project_id, type, source, title, text, date, outcome, skills,
score} (+ client_industry, project_ids).

Indexes are built once per (portfolio, embedder) per process: the persisted index under
data/processed/index/<portfolio>/ is loaded, synced against data/personas/<portfolio>/ (hash-based:
only new/changed documents are embedded) and saved back.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol

from rag import config
from rag.embedder import Embedder, get_embedder
from rag.index.store import ContextFn, PersonaIndex
from rag.ingest.loaders import load_persona
from rag.pipeline import Pipeline
from rag.types import Document
from rag.variants import spec_from_name

log = logging.getLogger(__name__)
_INDEXES: dict[tuple[str, str, str], PersonaIndex] = {}
_LOCK = threading.Lock()


class Retriever(Protocol):
    def search(self, requirement: str, k: int = 5, filters: dict | None = None) -> list[dict]: ...

    def search_job(self, job_spec: dict, k: int = 5) -> list[dict]: ...


def build_index(persona: str, *, embedder: Embedder | None = None, personas_dir: Path | None = None,
                index_root: Path | None = None, persist: bool = True,
                context_fn: ContextFn | None = None) -> PersonaIndex:
    """Load the persisted index, sync it with the persona's files, save if anything changed."""
    embedder = embedder or get_embedder()
    root = index_root or config.index_root()
    idx = PersonaIndex.load(persona, embedder, root, context_fn=context_fn)
    pdir = (personas_dir or config.personas_root()) / persona
    if pdir.is_dir():
        stats = idx.sync(load_persona(pdir, persona))
        if persist and (stats["added"] or stats["updated"] or stats["removed"]):
            idx.save()
            log.info("index %s synced: %s", persona, stats)
    return idx


def get_index(portfolio_id: str, *, embedder: Embedder | None = None, refresh: bool = False,
              **kwargs) -> PersonaIndex:
    embedder = embedder or get_embedder()
    key = (portfolio_id, embedder.name, str(config.index_root()))
    with _LOCK:
        if refresh or key not in _INDEXES:
            _INDEXES[key] = build_index(portfolio_id, embedder=embedder, **kwargs)
        return _INDEXES[key]


def add_document(portfolio_id: str, doc: Document, *, persist: bool = True) -> str:
    """Incremental re-index when the user adds work in the UI: only this document is embedded."""
    idx = get_index(portfolio_id)
    result = idx.add_document(doc)
    if persist and result != "unchanged":
        idx.root = idx.root or config.index_root()
        idx.save()
    return result


def clear_cache() -> None:
    with _LOCK:
        _INDEXES.clear()


def get_retriever(variant: str | None = None, portfolio_id: str | None = None, *,
                  index: PersonaIndex | None = None, cfg: dict | None = None, **kwargs
                  ) -> Pipeline:
    variant = variant or config.default_variant()
    if index is None:
        portfolio_id = portfolio_id or config.default_portfolio_id()
        if not portfolio_id:
            raise ValueError("portfolio_id not given and env PORTFOLIO_ID is unset")
        index = get_index(portfolio_id)
    return Pipeline(index, spec_from_name(variant), name=variant, cfg=cfg, **kwargs)
