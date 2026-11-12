"""Variant registry. Names compose with "+": ``v1_decompose+v2_hybrid+v3_rerank``.

Each module exposes ``NAME``, ``ALIASES``, ``OVERRIDES`` (the PipelineSpec fields it changes) and
``build(index, cfg) -> Pipeline``. Unmodified specs are the structure-aware chunk baseline
(``struct``); ``v0_naive`` switches to fixed chunks. ``v0b_naive_struct`` = the same dense
whole-post query over structure-aware chunks (control that isolates the chunking effect).
"""
from __future__ import annotations

from rag.pipeline import PipelineSpec
from rag.variants import (
    v0_naive,
    v1_decompose,
    v2_hybrid,
    v3_rerank,
    v4_outcome,
    v5_multivector,
    v6_contextual,
    v7_hyde,
    v8_corrective,
    v9_skill_graph,
)

MODULES = (v0_naive, v1_decompose, v2_hybrid, v3_rerank, v4_outcome, v5_multivector,
           v6_contextual, v7_hyde, v8_corrective, v9_skill_graph)
TOKENS: dict[str, dict] = {
    "v0b_naive_struct": {}, "struct": {}, "dense": {"retrieval": "dense"},
    "whole": {"query": "whole"}, "fixed": {"scheme": "fixed"},
}
for _m in MODULES:
    TOKENS[_m.NAME] = _m.OVERRIDES
    for _a in _m.ALIASES:
        TOKENS[_a] = _m.OVERRIDES
VARIANT_NAMES = [m.NAME for m in MODULES]


def spec_from_name(variant: str) -> PipelineSpec:
    """Parse "v2_hybrid" or a composition "v1_decompose+hybrid+rerank" into a PipelineSpec."""
    fields: dict = {}
    for token in variant.replace(" ", "").split("+"):
        if token not in TOKENS:
            raise ValueError(f"unknown RAG variant/component {token!r}; known: {sorted(TOKENS)}")
        fields.update(TOKENS[token])
    return PipelineSpec(**fields)
