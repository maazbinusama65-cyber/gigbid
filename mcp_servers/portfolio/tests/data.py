"""Fixture portfolio on disk (same layout as data/personas/<id>)."""
from __future__ import annotations

import json
from pathlib import Path


def make_portfolio(root: Path, pid: str = "ai_ml") -> Path:
    d = root / pid
    (d / "case_studies").mkdir(parents=True)
    (d / "repos" / "churn").mkdir(parents=True)
    (d / "case_studies" / "churn.md").write_text(
        "# Churn prediction for a telco\n\nBuilt a gradient boosting churn model with scikit-learn "
        "and SHAP. Lift of 2.1x on the top decile.\n\nDeployed behind FastAPI on Docker.",
        encoding="utf-8")
    (d / "case_studies" / "rag.md").write_text(
        "# RAG over contracts\n\nHybrid BM25 plus dense retrieval with a cross-encoder reranker "
        "over 40k PDF contracts. Cut review time by 60 percent.", encoding="utf-8")
    (d / "repos" / "churn" / "README.md").write_text("# churn\nPipeline code, pandas, sklearn.")
    (d / "projects.json").write_text(json.dumps([
        {"project_id": "churn", "title": "Churn prediction", "skills": ["Python", "scikit-learn", "FastAPI"],
         "industry": "telecom", "date": "2024-05", "outcome_summary": "2.1x lift", "aliases": []},
        {"project_id": "rag", "title": "Contract RAG", "skills": ["Python", "RAG", "FastAPI"],
         "industry": "legal", "date": "2025-02", "outcome_summary": "60% faster review", "aliases": []},
    ]), encoding="utf-8")
    (d / "reviews.json").write_text(json.dumps([
        {"review_id": "r1", "project_id": "churn", "client_industry": "telecom", "rating": 5,
         "text": "Great communication and a model that actually shipped.", "date": "2024-06-01"}]))
    (d / "proposals.json").write_text(json.dumps([
        {"proposal_id": "p1", "job_title": "Churn model", "text": "I built a churn model with scikit-learn.",
         "outcome": "won", "date": "2024-04-01", "project_ids": ["churn"], "client_industry": "telecom",
         "category": "ml"},
        {"proposal_id": "p2", "job_title": "Chatbot", "text": "Generic chatbot proposal text.",
         "outcome": "ignored", "date": "2024-09-01", "project_ids": [], "client_industry": "retail",
         "category": "nlp"}]))
    (d / "cv.md").write_text("# CV\n\nML engineer. Python, scikit-learn, RAG, FastAPI.")
    return root
