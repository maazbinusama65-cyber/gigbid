import math

from evals import metrics as m


def test_recall_mrr_ndcg_known_values():
    ranked = ["a", "x", "b", "y"]
    gold = {"a", "b"}
    assert m.recall_at_k(ranked, gold, 2) == 0.5
    assert m.recall_at_k(ranked, gold, 5) == 1.0
    assert m.mrr(ranked, gold) == 1.0
    assert m.mrr(["x", "b"], gold) == 0.5
    # perfect ranking has ndcg 1
    assert m.ndcg_at_k(["a", "b", "x"], gold, 10) == 1.0
    assert 0 < m.ndcg_at_k(ranked, gold, 10) < 1
    assert math.isnan(m.recall_at_k(ranked, set(), 5))


def test_binary_prf():
    r = m.binary_prf([True, True, False, False], [True, False, True, False])
    assert (r["tp"], r["fp"], r["fn"]) == (1, 1, 1) and r["f1"] == 0.5


def test_kappa_perfect_and_chance():
    assert m.cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    assert m.cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == 0.0


def test_two_proportion_z_detects_difference():
    r = m.two_proportion_z(60, 100, 40, 100)
    assert r["p"] < 0.01
    assert m.two_proportion_z(50, 100, 50, 100)["p"] == 1.0


def test_percentile_and_wilson():
    assert m.percentile([1, 2, 3, 4, 5], 0.5) == 3
    lo, hi = m.wilson(50, 100)
    assert lo < 0.5 < hi
