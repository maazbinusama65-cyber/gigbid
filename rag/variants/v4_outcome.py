"""V4 - Ranking: boost proposals that won/replied and the projects they cite."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v4_outcome"
ALIASES = ('outcome',)
OVERRIDES = {'outcome': True}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
