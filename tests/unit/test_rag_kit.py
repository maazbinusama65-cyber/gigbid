"""Shared helpers for the offline RAG unit tests (hash embedder, lexical reranker, fixture)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from rag.embedder import HashEmbedder
from rag.index.store import PersonaIndex
from rag.ingest.loaders import load_persona
from rag.rerank import LexicalReranker

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "rag"


@lru_cache(maxsize=1)
def fixture_docs():
    return tuple(load_persona(FIXTURE / "personas" / "ai_ml", "ai_ml"))


def fixture_index(root: Path | None = None) -> PersonaIndex:
    idx = PersonaIndex("ai_ml", HashEmbedder(), root=root)
    idx.add_documents(list(fixture_docs()))
    return idx


def fixture_jobs() -> dict[str, dict]:
    return {j["job_id"]: j for j in map(json.loads, (FIXTURE / "jobs.jsonl").read_text().splitlines())}


def fixture_dev() -> dict[str, dict]:
    return {r["job_id"]: r for r in map(json.loads,
                                        (FIXTURE / "dev_ai_ml.jsonl").read_text().splitlines())}


RERANKER = LexicalReranker()
