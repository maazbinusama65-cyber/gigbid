"""V7 - Query: retrieve with a hypothetical ideal proposal (generator pluggable)."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v7_hyde"
ALIASES = ('hyde',)
OVERRIDES = {'query': 'hyde'}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
