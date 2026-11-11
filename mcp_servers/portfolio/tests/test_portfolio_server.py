from __future__ import annotations

import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from mcp_servers.portfolio import build_server
from mcp_servers.portfolio.service import PortfolioConfig

pytestmark = pytest.mark.asyncio


class FakeRetriever:
    name = "fake"

    def __init__(self):
        self.calls = []

    def search(self, requirement, k=5, filters=None):
        self.calls.append((requirement, k, filters))
        return [{"id": "e1", "type": "proposal", "text": "did X", "outcome": "won", "score": 0.9,
                 "project_id": "churn"}]


async def test_tools_listed_with_read_only_annotations(server):
    async with connect(server) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    assert set(tools) == {"search_evidence", "get_case_study", "list_skills"}
    for t in tools.values():
        a = t.annotations
        assert a.readOnlyHint is True and a.destructiveHint is False
        assert a.idempotentHint is True and a.openWorldHint is False
        assert t.outputSchema is not None


async def test_search_uses_injected_retriever_and_filters(portfolio_dir):
    fake = FakeRetriever()
    srv = build_server(PortfolioConfig(data_dir=str(portfolio_dir), default_portfolio_id="ai_ml"),
                       retriever=fake)
    async with connect(srv) as c:
        r = await c.call_tool("search_evidence", {
            "requirement": "churn model", "k": 3, "filters": {"outcome": "won", "types": ["proposal"]}})
    assert not r.isError
    assert r.structuredContent["items"][0]["id"] == "e1"
    assert r.structuredContent["retriever"] == "fake"
    assert fake.calls == [("churn model", 3, {"outcome": "won", "types": ["proposal"]})]


async def test_local_retriever_ranks_relevant_case_study(server):
    async with connect(server) as c:
        r = await c.call_tool("search_evidence", {"requirement": "hybrid retrieval reranker for PDF contracts"})
    items = r.structuredContent["items"]
    assert items and items[0]["project_id"] == "rag"
    assert items[0]["type"] == "case_study" and items[0]["date"] == "2025-02"


async def test_local_retriever_filters(server):
    async with connect(server) as c:
        r = await c.call_tool("search_evidence", {
            "requirement": "churn scikit-learn", "filters": {"types": ["proposal"], "outcome": "won"}})
    items = r.structuredContent["items"]
    assert [i["id"] for i in items] == ["proposal:p1"]
    assert items[0]["outcome"] == "won"


async def test_no_match_returns_empty_not_invented(server):
    async with connect(server) as c:
        r = await c.call_tool("search_evidence", {"requirement": "kubernetes operators in rust"})
    assert r.structuredContent["items"] == []


async def test_input_constraints_rejected(server):
    async with connect(server) as c:
        bad = [
            {"requirement": "x"},  # too short
            {"requirement": "valid text", "k": 0},
            {"requirement": "valid text", "k": 99},
            {"requirement": "valid text", "filters": {"bogus": 1}},
            {"requirement": "valid text", "portfolio_id": "../etc"},
        ]
        for args in bad:
            r = await c.call_tool("search_evidence", args)
            assert r.isError, args


async def test_get_case_study_and_not_found(server):
    async with connect(server) as c:
        r = await c.call_tool("get_case_study", {"id": "churn"})
        assert r.structuredContent["title"] == "Churn prediction"
        assert r.structuredContent["related_proposal_ids"] == ["p1"]
        assert r.structuredContent["reviews"][0]["rating"] == 5
        miss = await c.call_tool("get_case_study", {"id": "nope"})
        assert miss.isError and "not_found" in miss.content[0].text
        trav = await c.call_tool("get_case_study", {"id": "../projects"})
        assert trav.isError


async def test_list_skills_counts(server):
    async with connect(server) as c:
        r = await c.call_tool("list_skills", {})
    sk = {s["name"]: s["count"] for s in r.structuredContent["skills"]}
    assert sk["Python"] == 2 and sk["RAG"] == 1


async def test_resources_and_templates(server):
    async with connect(server) as c:
        tmpl = {t.uriTemplate for t in (await c.list_resource_templates()).resourceTemplates}
        assert {"portfolio://case/{id}", "portfolio://proposal/{id}"} <= tmpl
        case = await c.read_resource("portfolio://case/rag")
        assert "Hybrid BM25" in case.contents[0].text
        prop = await c.read_resource("portfolio://proposal/p1")
        assert json.loads(prop.contents[0].text)["outcome"] == "won"


async def test_prompts_embed_grounding_and_evidence(server):
    async with connect(server) as c:
        names = {p.name for p in (await c.list_prompts()).prompts}
        assert {"screening_answer", "cover_letter_from_evidence"} <= names
        p = await c.get_prompt("screening_answer", {"question": "Have you built churn models?"})
    text = p.messages[0].content.text
    assert "ONLY the evidence" in text and "case:churn" in text


async def test_missing_portfolio_is_clean_error(portfolio_dir):
    srv = build_server(PortfolioConfig(data_dir=str(portfolio_dir), default_portfolio_id="ghost",
                                       backend="local"))
    async with connect(srv) as c:
        r = await c.call_tool("search_evidence", {"requirement": "anything at all"})
    assert r.isError and "not_found" in r.content[0].text
