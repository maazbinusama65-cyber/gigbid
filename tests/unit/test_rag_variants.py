"""B2: every variant builds, honours the result contract and behaves as designed (offline)."""
from __future__ import annotations

import pytest

from rag.index.skillgraph import SkillGraph
from rag.metrics import job_metrics, ndcg_at_k, ranked_projects, recall_at_k
from rag.query import extract_requirements, template_hyde
from rag.retriever import get_retriever
from rag.types import RESULT_KEYS
from rag.variants import VARIANT_NAMES, spec_from_name
from tests.unit.test_rag_kit import RERANKER, fixture_dev, fixture_index, fixture_jobs

IDX = fixture_index()


def retr(variant: str, **kw):
    if "corrective" in variant and "cfg" not in kw:  # hash-embedder cosines are not bge cosines
        kw["cfg"] = {"corrective": {"strong": 0.0, "weak": 0.0}}
    return get_retriever(variant, index=IDX, reranker=RERANKER, **kw)


def test_ten_variants_registered():
    assert VARIANT_NAMES == ["v0_naive", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome",
                             "v5_multivector", "v6_contextual", "v7_hyde", "v8_corrective",
                             "v9_skill_graph"]


@pytest.mark.parametrize("variant", VARIANT_NAMES + ["v1_decompose+v2_hybrid+v3_rerank"])
def test_result_contract(variant):
    items = retr(variant).search("We need Celery workers with Redis and retries", k=5)
    assert 1 <= len(items) <= 5
    for it in items:
        assert set(RESULT_KEYS) <= set(it)
        assert isinstance(it["skills"], list) and isinstance(it["score"], float)
    assert "p05" in [i["project_id"] for i in items]


@pytest.mark.parametrize("variant", VARIANT_NAMES)
def test_search_job_recovers_gold_on_fixture(variant):
    jobs, dev = fixture_jobs(), fixture_dev()
    r = retr(variant)
    for jid in ("j1", "j3", "j6"):
        gold = set(dev[jid]["gold_project_ids"])
        items = r.search_job(jobs[jid], k=20, max_per_project=None)
        m = job_metrics(items, gold)
        assert m["recall5"] >= 0.5, (variant, jid, m["ranked"])


def test_composition_and_unknown_component():
    spec = spec_from_name("v1_decompose+v2_hybrid+v3_rerank")
    assert (spec.query, spec.retrieval, spec.rerank, spec.scheme) == (
        "decompose", "hybrid", True, "struct")
    assert spec_from_name("v0_naive").scheme == "fixed"
    assert spec_from_name(spec.label()) == spec  # labels round-trip (ablation relies on it)
    with pytest.raises(ValueError):
        spec_from_name("v1_decompose+nonsense")


def test_env_variant_override(monkeypatch):
    monkeypatch.setenv("RAG_VARIANT", "v2_hybrid")
    assert get_retriever(index=IDX).variant == "v2_hybrid"


def test_v0_uses_fixed_chunks_and_others_structured():
    assert retr("v0_naive").search("Prophet forecasting", k=1)[0]["id"].split("#")[-1].startswith("f")
    assert retr("v2_hybrid").search("Prophet forecasting", k=1)[0]["id"].split("#")[-1].startswith("s")


def test_decompose_splits_requirements():
    job = {"description": "We need demand forecasting with Prophet. Build a RAG chatbot using "
                          "Pinecone and LangChain. It must answer questions about forecasts.",
           "required_skills": ["Docker"]}
    reqs = extract_requirements(job)
    assert len(reqs) >= 3 and any("Pinecone" in r for r in reqs) and reqs[-1] == "experience with Docker"
    bullets = {"description": "What we need:\n- Build a Celery pipeline\n- Deploy on AWS Lambda",
               "required_skills": ["Celery"]}
    assert extract_requirements(bullets) == ["Build a Celery pipeline", "Deploy on AWS Lambda"]
    assert extract_requirements({"requirements": ["a thing", "other"]}) == ["a thing", "other"]


def test_hybrid_matches_exact_tool_name():
    top = retr("v2_hybrid").search("Pinecone", k=3)
    assert top[0]["project_id"] == "p02"


def test_filters_applied_in_search():
    items = retr("v2_hybrid").search("forecasting", k=5, filters={"type": "proposal"})
    assert items and all(i["type"] == "proposal" for i in items)
    items = retr("v2_hybrid").search("ingestion", k=5, filters={"project_id": "p05"})
    assert items and all("p05" in (i["project_ids"] or [i["project_id"]]) for i in items)


def test_outcome_boosts_winning_proposal_over_ignored():
    # pr1 (won) and pr5 (ignored) are equally close to this query; the won one must rank higher
    items = retr("v4_outcome").search("proposal for forecasting API and Celery ingestion", k=10,
                                      filters={"type": "proposal"})
    ids = [i["id"] for i in items]
    won = next(i for i in ids if "pr1#" in i)
    ignored = next(i for i in ids if "pr5#" in i)
    assert ids.index(won) < ids.index(ignored)


def test_multivector_returns_one_item_per_project():
    items = retr("v5_multivector").search("Celery", k=5)
    pids = [i["project_id"] for i in items if i["project_id"]]
    assert len(pids) == len(set(pids))


def test_contextual_chunks_embed_context_line():
    view = IDX.view("ctx")
    rec = next(r for r in view.records if r["type"] == "code" and r["project_id"] == "p05")
    assert "Celery ingestion workers" in rec["ctx"] and "fintech" in rec["ctx"]


def test_hyde_generator_is_pluggable():
    seen = []

    def gen(job):
        seen.append(job)
        return "I built a Celery and Redis ingestion system"

    r = retr("v7_hyde", hyde_fn=gen)
    assert r.search_job({"title": "vague", "description": "need help with data"}, k=3)[0][
        "project_id"] == "p05" and seen
    assert "Thanks for posting Foo" in template_hyde({"title": "Foo", "description": "do a thing now"})


def test_corrective_refuses_when_no_evidence_and_reports_uncovered():
    r = retr("v8_corrective", cfg={"corrective": {"strong": 0.9, "weak": 0.8}})
    out = r.search_job_detailed(fixture_jobs()["j7"], k=5)
    assert out["refused"] and out["items"] == []
    ok = retr("v8_corrective", cfg={"corrective": {"strong": 0.0, "weak": 0.0}})
    out = ok.search_job_detailed(fixture_jobs()["j1"], k=5)
    assert not out["refused"] and out["items"] and out["trace"]["path"][0] == "plan"


def test_corrective_loop_rewrites_weak_requirements():
    r = retr("v8_corrective", cfg={"corrective": {"strong": 2.0, "weak": 0.0, "max_rewrites": 2}})
    out = r.search_job_detailed(fixture_jobs()["j2"], k=5)
    assert out["trace"]["rewrites"] == 2
    assert out["trace"]["path"].count("retrieve") == 3


def test_skill_graph_answers_experience_question():
    g = SkillGraph(IDX.view("mv").records)
    hit = g.experience("Python", "retail")
    assert [h["project_id"] for h in hit] == ["p01"] and hit[0]["won"] == 1
    assert g.experience("Python", "healthcare") == []
    scores = g.score_projects("We need Celery and Redis workers")
    assert max(scores, key=scores.get) == "p05"


def test_metrics_project_level():
    items = [{"type": "case_study", "project_id": "a"}, {"type": "cv", "project_id": None},
             {"type": "proposal", "project_id": "b", "project_ids": ["b", "c"]},
             {"type": "code", "project_id": "a"}]
    assert ranked_projects(items) == ["a", "b", "c"]
    assert ranked_projects(items, "none") == ["a"]
    assert recall_at_k(["a", "b", "c"], {"a", "z"}, 5) == 0.5
    assert ndcg_at_k(["z", "a"], {"a"}) == pytest.approx(1 / 1.5849625, rel=1e-4)
