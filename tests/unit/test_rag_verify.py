"""B3: claim splitting, grounding and repair on adversarial drafts (offline, hash embedder)."""
from __future__ import annotations

import pytest

from agent.handoffs import Claim
from rag.embedder import HashEmbedder
from rag.verify import (
    extract_numbers,
    is_checkable,
    split_clauses,
    verify_and_repair,
    verify_and_repair_detailed,
    verify_claims,
)

EVIDENCE = [
    {"id": "e1", "project_id": "p01", "type": "case_study", "title": "Demand forecasting API",
     "text": "I built a time series forecasting service with Prophet and scikit-learn exposed "
             "through FastAPI. Stock-outs fell by 18 percent within two months for a grocery chain.",
     "skills": ["Python", "FastAPI", "Prophet"], "outcome": None, "score": 0.9},
    {"id": "e2", "project_id": "p02", "type": "case_study", "title": "Support-docs RAG chatbot",
     "text": "I built a retrieval augmented generation chatbot using LangChain and Pinecone. The "
             "bot deflected 35 percent of tier-1 tickets. Freelance ML engineer 2021-present.",
     "skills": ["LangChain", "Pinecone"], "outcome": None, "score": 0.8},
]
TRUE_DRAFT = ("I built a Prophet forecasting API with FastAPI for a grocery chain. "
              "Stock-outs fell by 18 percent. I shipped a LangChain and Pinecone chatbot.")


@pytest.fixture(autouse=True)
def _hash_embedder(monkeypatch):
    monkeypatch.setenv("RAG_EMBEDDER", "hash")


def repair(text, **kw):
    return verify_and_repair_detailed(text, EVIDENCE, embedder=HashEmbedder(), this_year=2026, **kw)


def test_graph_facing_signature_returns_text_and_claim_records():
    text, records = verify_and_repair(TRUE_DRAFT + " I invented Zorblax Corp.", EVIDENCE)
    assert isinstance(text, str) and records
    assert set(records[0]) == {"text", "label", "evidence_ids", "rewritten", "removed"}
    Claim(**records[0])  # records are valid agent.handoffs.Claim payloads
    assert verify_and_repair(TRUE_DRAFT, EVIDENCE, None)[0] == TRUE_DRAFT


def test_true_claims_are_supported_and_text_unchanged():
    res = repair(TRUE_DRAFT)
    assert res.repaired == TRUE_DRAFT
    assert {c.label for c in res.claims} == {"supported"}
    assert res.claims[0].evidence_ids == ["e1"]
    assert res.stats["unsupported_rate_before"] == 0


def test_invented_client_name_is_dropped_but_claim_kept():
    res = repair("I deployed a LangChain chatbot for Globex Industries.")
    assert "Globex" not in res.repaired and "LangChain chatbot" in res.repaired
    assert res.claims[0].label == "partly_supported" and res.claims[0].rewritten


def test_invented_years_of_experience_never_survive():
    res = repair("I have 12 years of experience with Prophet.")
    assert "12" not in res.repaired
    assert res.stats["with_invented_specifics_before"] == 1
    assert res.stats["with_invented_specifics_after"] == 0


def test_invented_metric_is_removed_or_rewritten_without_the_number():
    res = repair("I built a Prophet forecasting API that boosted revenue by 73%.")
    assert "73" not in res.repaired
    res = repair("Stock-outs fell by 40 percent using Prophet.")
    assert "40" not in res.repaired


def test_fully_fabricated_claim_is_removed():
    res = repair("I built a blockchain wallet for Binance that processed 9 million trades.")
    assert res.repaired.strip() == "" and res.claims[0].removed
    assert res.claims[0].label == "unsupported"


def test_mixed_draft_rate_before_after():
    draft = (TRUE_DRAFT + "\nI built a recommender for Acme Corp that raised sales by 45%. "
             "I have 9 years of experience with Kubernetes. I deployed a LangChain chatbot for "
             "Globex Industries.\nHappy to chat. Do you have a deadline?")
    res = repair(draft)
    assert res.stats["ungrounded_rate_before"] >= 0.5
    assert res.stats["ungrounded_rate_after"] == 0.0
    for bad in ("Acme", "45%", "9 years", "Kubernetes"):
        assert bad not in res.repaired
    assert "Happy to chat." in res.repaired and "Do you have a deadline?" in res.repaired
    assert "\n" in res.repaired  # paragraph structure preserved


def test_numbers_match_by_value_unit_and_word_forms():
    ev = [{"id": "x", "title": "", "text": "Handled two million transactions per day in 3 months.",
           "skills": []}]
    ok = verify_claims("I handled 2M transactions per day.", ev, embedder=HashEmbedder())
    assert ok[0]["label"] != "unsupported" and not ok[0]["invented"]
    bad = verify_claims("I handled 5M transactions per day.", ev, embedder=HashEmbedder())
    assert bad[0]["invented"]
    assert [n.value for n in extract_numbers("a 35% lift and $1,200 spend")] == [35.0, 1200.0]


def test_years_supported_from_date_span_in_evidence():
    res = repair("I have 5 years of experience as a freelance ML engineer.")
    assert "5 years" in res.repaired


def test_non_claims_not_graded():
    assert not is_checkable("Do you have a deadline?")
    assert not is_checkable("Looking forward to hearing from you.")
    assert not is_checkable("Hello,")
    assert is_checkable("I built a forecasting API for a grocery chain.")
    assert len(split_clauses("I built an API; I also tuned the model.")) == 2


def test_injected_llm_judge_overrides_semantics_but_not_invented_specifics():
    def judge(claim, evidence):
        return {"label": "supported", "evidence_ids": ["e2"]}

    res = repair("I built a payments gateway.", judge=judge)  # judge says supported
    assert res.claims[0].label == "supported" and res.claims[0].evidence_ids == ["e2"]
    res = repair("I built a payments gateway for Initech.", judge=judge)  # invented name vetoes
    assert res.claims[0].label == "partly_supported"
    res = repair(TRUE_DRAFT, judge=lambda c, e: "unsupported")
    assert res.repaired.strip() == ""
