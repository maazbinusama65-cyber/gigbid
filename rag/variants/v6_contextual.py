"""V6 - Indexing: a context line (template by default, LLM optional) prepended to each chunk."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v6_contextual"
ALIASES = ('contextual', 'ctx')
OVERRIDES = {'scheme': 'ctx'}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
