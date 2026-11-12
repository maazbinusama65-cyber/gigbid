"""V0 - Baseline (required): fixed-size chunks, top-k cosine on the whole job post."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v0_naive"
ALIASES = ('naive',)
OVERRIDES = {'scheme': 'fixed'}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
