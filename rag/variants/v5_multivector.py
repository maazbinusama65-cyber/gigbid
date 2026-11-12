"""V5 - Indexing: summary, README, code, narrative indexed separately; one result per project."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v5_multivector"
ALIASES = ('multivector', 'mv')
OVERRIDES = {'scheme': 'mv'}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
