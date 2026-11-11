"""Harness checks for the tool-granularity eval (no model involved)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evals.runners import tool_design_eval as ev


@pytest.fixture(scope="module")
async def sets():
    return ev.build_sets(await ev.load_best_tools())


def test_task_file_has_40_wellformed_tasks():
    tasks = ev.load_tasks()
    assert len(tasks) == 40 and len({t["id"] for t in tasks}) == 40
    for t in tasks:
        assert t["task"] and t["gold"]["tool"] and isinstance(t["gold"]["args"], dict)
    assert len({t["gold"]["tool"] for t in tasks}) == 17  # every real tool is exercised


async def test_gold_calls_exist_in_every_tool_set(sets):
    tasks = ev.load_tasks()
    for ts in sets:
        names = {t.name for t in ts.tools}
        for t in tasks:
            gold = ts.translate(t)
            assert gold["tool"] in names, (ts.name, t["id"], gold["tool"])
            props = next(x for x in ts.tools if x.name == gold["tool"]).input_schema["properties"]
            assert set(gold["args"]) <= set(props), (ts.name, t["id"], set(gold["args"]) - set(props))


async def test_set_sizes_and_best_is_the_real_surface(sets):
    by = {s.name: s for s in sets}
    assert len(by["fine"].tools) == 35 and len(by["coarse"].tools) == 4 and len(by["best"].tools) == 17
    assert {t.name for t in by["best"].tools} == {t.name for t in by["best_terse_descriptions"].tools}
    assert all(len(t.description) > 60 for t in by["best"].tools)
    assert all(len(t.description) < 40 for t in by["best_terse_descriptions"].tools)


async def test_oracle_selector_scores_100_percent_everywhere(sets):
    """A chat function that answers with the gold call must score 1.0: proves scoring + gold agree."""
    tasks = ev.load_tasks()
    by_task = {t["task"]: t for t in tasks}

    class Oracle(ev.LLMSelector):
        def __init__(self, ts):
            super().__init__(chat=lambda s, u: json.dumps(ts.translate(by_task[u])), name="oracle")

    for ts in sets:
        out = await ev.evaluate_set(Oracle(ts), ts, tasks, lambda s: len(s) // 4)
        assert out["tool_selection_accuracy"] == 1.0 and out["argument_accuracy"] == 1.0, ts.name


async def test_wrong_tool_and_wrong_args_are_scored_wrong(sets):
    by = {s.name: s for s in sets}["best"]
    task = ev.load_tasks()[4]  # get_job job-1042
    gold = by.translate(task)
    assert ev.score_task(gold, ev.Selection("get_job", {"job_id": "job-1042"})) == {"tool_ok": True, "args_ok": True}
    assert ev.score_task(gold, ev.Selection("get_job", {"job_id": "job-1"}))["args_ok"] is False
    assert ev.score_task(gold, ev.Selection("get_client_history", {"client_id": "x"}))["tool_ok"] is False
    assert ev.score_task(gold, ev.Selection(None, {}))["tool_ok"] is False


def test_value_matching_rules():
    assert ev.values_match(["Python", "SQL"], ["sql", "python"])
    assert ev.values_match("built a RAG pipeline over PDFs", "I have built a RAG pipeline over PDFs")
    assert not ev.values_match("built a RAG pipeline over PDFs", "something else entirely")
    assert ev.values_match({"outcome": "won"}, {"outcome": "won", "types": ["proposal"]})
    assert ev.values_match(450, 450.0) and ev.values_match(True, True) and not ev.values_match(True, "true")
    assert ev.args_match({"job_id": "j1"}, {"job_id": "j1", "idempotency_key": "zzz", "extra": 1})


def test_parse_selection_handles_fences_and_garbage():
    assert ev.parse_selection('```json\n{"tool": "get_job", "args": {"job_id": "j"}}\n```').tool == "get_job"
    assert ev.parse_selection("I think get_job").tool is None
    assert ev.parse_selection('{"name": "x", "arguments": {"a": 1}}').args == {"a": 1}


async def test_baseline_run_is_labelled_as_baseline_not_llm(sets, tmp_path):
    res = await ev.run_eval(ev.OfflineBaselineSelector(), sets=sets)
    assert res["meta"]["selector"] == "offline-baseline" and res["meta"]["model"] is None
    assert "NOT an LLM" in res["meta"]["WARNING"]
    assert set(res["sets"]) == {"fine", "coarse", "best", "best_terse_descriptions"}
    for s in res["sets"].values():
        assert s["n_tasks"] == 40 and 0 <= s["tool_selection_accuracy"] <= 1 and s["tokens_per_task"] > 0
    # many tiny schemas cost more tokens than a few coarse ones, and rich descriptions cost the most
    assert res["sets"]["coarse"]["schema_tokens"] < res["sets"]["fine"]["schema_tokens"]
    assert res["sets"]["best"]["schema_tokens"] > res["sets"]["best_terse_descriptions"]["schema_tokens"]
    path = ev.write_results(res, tmp_path / "out.json")
    assert json.loads(path.read_text())["meta"]["selector"] == "offline-baseline"


async def test_llm_selector_run_is_labelled_llm(sets):
    ts = [s for s in sets if s.name == "coarse"]
    res = await ev.run_eval(ev.LLMSelector(lambda s, u: '{"tool": "portfolio", "args": {"action": "skills"}}',
                                           name="scripted", model="m-1"), sets=ts)
    assert res["meta"]["selector"] == "llm" and res["meta"]["model"] == "m-1" and "WARNING" not in res["meta"]


async def test_failing_model_call_counts_as_wrong_not_crash(sets):
    def boom(s, u):
        raise TimeoutError("model down")

    res = await ev.run_eval(ev.LLMSelector(boom), sets=[sets[0]], tasks=ev.load_tasks()[:3])
    assert res["sets"]["fine"]["tool_selection_accuracy"] == 0.0
    assert "TimeoutError" in res["sets"]["fine"]["per_task"][0]["error"]


async def test_stub_llm_is_refused_as_an_llm_result():
    class StubLLM:
        async def chat(self, node, system, user, **kw):
            return SimpleNamespace(text="{}", stub=True, model="stub")

    chat, _ = ev.llm_client_chat_fn(StubLLM())
    with pytest.raises(RuntimeError, match="stub"):
        await chat("s", "u")
