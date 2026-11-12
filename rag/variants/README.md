# RAG variants

Each `vN_*.py` exposes `NAME`, `ALIASES`, `OVERRIDES` (the `PipelineSpec` fields it changes) and
`build(index, cfg) -> Pipeline`. `Pipeline` implements `search(requirement, k, filters)` and
`search_job(job_spec, k)` (docs/INTERFACES.md section 4). `rag/retriever.py::get_retriever(variant,
portfolio_id)` is the factory; the variant comes from `agent/config.yaml` `rag.variant`, env
`RAG_VARIANT` overrides it.

| ID | Module | What it changes |
|---|---|---|
| V0 | `v0_naive` | fixed 90-word chunks, dense top-k on the whole job post (baseline) |
| V1 | `v1_decompose` | one retrieval per requirement, merged with RRF |
| V2 | `v2_hybrid` | own BM25 + dense, reciprocal rank fusion |
| V3 | `v3_rerank` | cross-encoder rerank of candidates |
| V4 | `v4_outcome` | boost won/replied proposals and the projects they cite |
| V5 | `v5_multivector` | summary / README / code / narrative / evidence ranked separately, one result per project |
| V6 | `v6_contextual` | context line prepended to each chunk (template; LLM generator pluggable via `PersonaIndex(context_fn=...)`) |
| V7 | `v7_hyde` | retrieve with a hypothetical ideal proposal (`hyde_fn` pluggable) |
| V8 | `v8_corrective` | LangGraph grade / re-query / refuse loop (`rag/corrective.py`) |
| V9 | `v9_skill_graph` | skill-project-industry-outcome graph fused with the ranking (`rag/index/skillgraph.py`) |

Every unmodified variant other than V0 retrieves over structure-aware chunks, so `v0b_naive_struct`
(dense, whole post, structure chunks) is the control that separates the chunking effect from V1-V9.

Compose with `+`: `v1_decompose+v2_hybrid+v3_rerank` (aliases `decompose hybrid rerank outcome
multivector contextual hyde corrective skillgraph`; `dense whole fixed struct` switch a component
off). `PipelineSpec.label()` round-trips through `spec_from_name`, which is how the ablation toggles
one component at a time.

Result items: `{id, project_id, type, source, title, text, date, outcome, skills, score}` plus
`client_industry` and `project_ids`. `search_job_detailed()` also returns `refused`, `uncovered`
requirements and a trace (V8 grades, rewrites, path).
