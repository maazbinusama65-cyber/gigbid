# Ablation of `v1_decompose+v2_hybrid+v9_skill_graph`

**Hypothesis (pre-registered):** In the best pipeline, removing requirement decomposition causes the largest Recall@5 drop of any single component; removing the cross-encoder reranker costs MRR/nDCG@10 more than Recall@5.

Full pipeline: Recall@5 75.8, MRR 0.979, nDCG@10 0.876 (n=360).

| Component removed | Recall@5 | Δ points [95% CI] | MRR | Δ points | nDCG@10 | Δ points |
|---|---|---|---|---|---|---|
| skill graph fusion | 68.1 | -7.7 [-10.1, -5.3] | 0.909 | -7.1 | 0.808 | -6.9 |
| BM25 hybrid (hybrid -> dense only) | 73.9 | -1.9 [-3.2, -0.7] | 0.970 | -1.0 | 0.858 | -1.8 |
| structure-aware chunking (-> fixed chunks) | 76.2 | +0.4 [-0.6, +1.5] | 0.975 | -0.4 | 0.874 | -0.2 |
| query decomposition (decompose -> whole post) | 76.4 | +0.6 [-1.5, +2.5] | 0.989 | +1.0 | 0.871 | -0.5 |
