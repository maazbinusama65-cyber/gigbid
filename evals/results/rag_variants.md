# RAG variants (dev sets)

**Hypothesis (pre-registered):** Requirement decomposition plus hybrid retrieval (v1_decompose+v2_hybrid) raises project-level evidence Recall@5 by >= 15 points over V0 (v0_naive) on jobs with >= 4 requirements.

| Variant | Recall@5 | Recall@5 (capped) | MRR | nDCG@10 | Recall@5 (>=4 reqs) | p50 ms | p95 ms | refusal recall / false refusal |
|---|---|---|---|---|---|---|---|---|
| v0_naive | 64.2 | 68.0 | 0.968 | 0.779 | 60.5 | 1300 | 2347 | - |
| v0b_naive_struct | 62.0 | 65.5 | 0.966 | 0.765 | 58.7 | 1804 | 5471 | - |
| v1_decompose | 57.7 | 61.1 | 0.791 | 0.694 | 50.2 | 1699 | 4793 | - |
| v2_hybrid | 67.6 | 71.4 | 0.975 | 0.810 | 63.7 | 1234 | 2237 | - |
| v3_rerank | 61.4 | 64.8 | 0.979 | 0.717 | 58.7 | 5176 | 7029 | - |
| v4_outcome | 61.7 | 65.1 | 0.938 | 0.750 | 57.8 | 1395 | 2412 | - |
| v5_multivector | 63.8 | 67.5 | 0.959 | 0.792 | 60.0 | 844 | 1422 | - |
| v6_contextual | 65.0 | 68.6 | 0.979 | 0.773 | 60.6 | 834 | 1372 | - |
| v7_hyde | 65.1 | 68.9 | 0.977 | 0.800 | 60.3 | 788 | 1691 | - |
| v8_corrective | 57.5 | 60.8 | 0.899 | 0.715 | 57.7 | 2536 | 3776 | 50.8 / 7.2 |
| v9_skill_graph | 72.6 | 76.8 | 0.986 | 0.843 | 69.0 | 137 | 215 | - |
| v1_decompose+v2_hybrid | 68.1 | 71.9 | 0.909 | 0.808 | 60.5 | 183 | 424 | - |
| v1_decompose+v2_hybrid+v3_rerank | 72.5 | 76.6 | 0.945 | 0.840 | 63.8 | 4862 | 18635 | - |
| v1_decompose+v2_hybrid+v3_rerank+v4_outcome | 70.9 | 74.8 | 0.926 | 0.825 | 62.4 | 4439 | 9028 | - |
| v1_decompose+v2_hybrid+v3_rerank+v9_skill_graph | 76.7 | 81.1 | 0.980 | 0.886 | 68.0 | 4412 | 9210 | - |
| v1_decompose+v2_hybrid+v3_rerank+v8_corrective | 41.0 | 43.5 | 0.540 | 0.468 | 40.4 | 8113 | 21593 | 68.8 / 42.5 |

## Hypothesis test

```json
{
 "hypothesis_id": "H1",
 "n_jobs": 168,
 "baseline_recall5": 0.6050006871435443,
 "variant_recall5": 0.6052250824572253,
 "gain_points": 0.022439531368102963,
 "ci95_points": [
  -3.6174886621315196,
  3.6970899470899474
 ],
 "verdict": "NOT SUPPORTED"
}
```
