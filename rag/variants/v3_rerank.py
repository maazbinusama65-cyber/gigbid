"""V3 - Retrieval: cross-encoder rerank of the dense candidates (precision at small k)."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v3_rerank"
ALIASES = ('rerank',)
OVERRIDES = {'rerank': True}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
