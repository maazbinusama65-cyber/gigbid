"""V9 - Agentic: skill/project/industry/outcome graph fused with the dense ranking."""
from __future__ import annotations

from rag.pipeline import Pipeline, PipelineSpec

NAME = "v9_skill_graph"
ALIASES = ('skillgraph', 'graph')
OVERRIDES = {'graph': True}


def build(index, cfg: dict | None = None, **kwargs) -> Pipeline:
    """Build this variant over a PersonaIndex. Extra kwargs: embedder, reranker, hyde_fn."""
    return Pipeline(index, PipelineSpec(**OVERRIDES), name=NAME, cfg=cfg, **kwargs)
