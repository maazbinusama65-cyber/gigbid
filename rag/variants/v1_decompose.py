"""V1 - Query: one retrieval per extracted requirement, merged by RRF."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v1_decompose"
ALIASES = ('decompose',)
OVERRIDES = {'query': 'decompose'}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
