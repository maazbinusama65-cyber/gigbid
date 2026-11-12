"""V2 - Retrieval: BM25 + dense fused with reciprocal rank fusion."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v2_hybrid"
ALIASES = ('hybrid',)
OVERRIDES = {'retrieval': 'hybrid'}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
