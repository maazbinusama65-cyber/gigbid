"""B4 harness: rag_eval end-to-end on the fixture (offline), ablation helpers, judge calibration."""
from __future__ import annotations

import json

import pytest

from evals.runners import judge_calibration as jc
from evals.runners import rag_eval
from tests.unit.test_rag_kit import FIXTURE


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDER", "hash")


def test_rag_eval_end_to_end_on_fixture(tmp_path):
    payload = rag_eval.run(
        ["ai_ml"], ["v0_naive", "v1_decompose+v2_hybrid", "v2_hybrid", "v8_corrective"],
        dev_dir=FIXTURE, jobs_path=FIXTURE / "jobs.jsonl", personas_dir=FIXTURE / "personas",
        index_root=tmp_path / "idx", out_dir=tmp_path / "out", prefix="rag_variants", latency=False)
    assert list(payload)[0] == "hypothesis"  # pre-registered before any number
    out = tmp_path / "out"
    for name in ("rag_variants.json", "rag_variants.csv", "rag_variants.md",
                 "rag_variants_per_job.jsonl"):
        assert (out / name).exists()
    v = payload["variants"]["v2_hybrid"]
    assert v["overall"]["n_eval"] == 6  # j7 has no gold
    assert 0 <= v["overall"]["recall5"] <= 1
    assert set(v["by_n_requirements"]) <= {"1-3", "4-5", "6+"}
    assert payload["variants"]["v8_corrective"]["refusal"]["n_gold_empty"] == 1
    assert payload["hypothesis_test"]["n_jobs"] >= 1
    assert "| v2_hybrid |" in (out / "rag_variants.md").read_text()
    assert json.loads((out / "rag_variants.json").read_text())["protocol"]["embedder"].startswith("hash")


def test_smoke_subset_is_deterministic_and_bounded():
    rows = [{"i": i} for i in range(200)]
    assert rag_eval.smoke_subset(rows, 10) == rag_eval.smoke_subset(rows, 10)
    assert len(rag_eval.smoke_subset(rows, 10)) == 10
    assert rag_eval.bucket(2) == "1-3" and rag_eval.bucket(4) == "4-5" and rag_eval.bucket(9) == "6+"


def test_cohens_kappa_known_values():
    assert jc.cohens_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == pytest.approx(1.0)
    assert jc.cohens_kappa([1, 1, 0, 0], [1, 0, 1, 0]) == pytest.approx(0.0)
    # hand computed: po=0.70, pe=0.7*0.6+0.3*0.4=0.54 -> kappa=(0.70-0.54)/(1-0.54)
    a = [1] * 25 + [1] * 10 + [0] * 5 + [0] * 10
    b = [1] * 25 + [0] * 10 + [1] * 5 + [0] * 10
    assert jc.cohens_kappa(a, b) == pytest.approx(0.16 / 0.46)
    assert jc.cohens_kappa([1, 2, 5], [1, 2, 5], "quadratic", [1, 2, 3, 4, 5]) == pytest.approx(1.0)


def test_calibration_never_invents_labels(tmp_path):
    assert jc.build_report(None, None)["status"] == "awaiting human labels"
    assert "kappa" not in json.dumps(jc.build_report(None, {"a": 3}))
    assert jc.build_report({"a": 3}, None)["status"] == "awaiting judge scores"
    rep = jc.build_report({"a": 5, "b": 1, "c": 4}, {"a": 4, "b": 2, "c": 4})
    assert rep["status"] == "ok" and rep["n"] == 3 and "warning" in rep


def test_sample_items_stratified_and_label_cli(tmp_path):
    pdir = tmp_path / "personas"
    for persona in ("a", "b"):
        (pdir / persona).mkdir(parents=True)
        props = [{"proposal_id": f"{persona}{i}", "job_title": "t", "text": f"text {i}",
                  "outcome": ["won", "ignored"][i % 2]} for i in range(30)]
        (pdir / persona / "proposals.json").write_text(json.dumps(props))
    items = jc.sample_items(pdir, 30, seed=1)
    assert len(items) == 30 and len({i["item_id"] for i in items}) == 30
    assert {i["persona"] for i in items} == {"a", "b"}
    path = tmp_path / "items.json"
    jc.write_items(items, path)
    saved = json.loads(path.read_text())
    assert "outcome_hidden_from_labeller" not in saved["items"][0]  # labeller is blind to outcome
    answers = iter(["5", "s", "3", "q"])
    labels_path = tmp_path / "labels.json"
    jc.label_cli(path, labels_path, inp=lambda _: next(answers), out=lambda *_: None)
    labels = json.loads(labels_path.read_text())["labels"]
    assert sorted(labels.values()) == [3, 5]
    scores = jc.run_judge(saved["items"][:3], lambda text, title: 4, tmp_path / "judge.json")
    assert set(scores.values()) == {4}


def test_ablation_removes_one_component_at_a_time():
    from evals.runners import ablation
    from rag.variants import spec_from_name

    full = spec_from_name("v1_decompose+v2_hybrid+v3_rerank")
    removed = ablation._remove(full)
    assert len(removed) == 4  # decompose, hybrid, rerank, structure-aware chunking
    for label, spec in removed.items():
        changed = [k for k, v in spec.components().items() if v != full.components()[k]]
        assert len(changed) == 1, (label, changed)


def test_v8_calibration_grid_prefers_separating_thresholds():
    from evals.runners import rag_calibrate

    rows = [{"has_gold": False, "support": [0.5, 0.55]}, {"has_gold": False, "support": [0.6]},
            {"has_gold": True, "support": [0.8, 0.9]}, {"has_gold": True, "support": [0.85]}]
    best = rag_calibrate.grid(rows)[0]
    assert best["balanced_accuracy"] == 1.0 and 0.6 < best["weak"] <= 0.8
