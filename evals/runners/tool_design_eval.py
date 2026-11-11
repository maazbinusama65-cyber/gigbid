"""R&D question A: does tool granularity change agent behaviour?

Compares three tool sets on 40 tasks with known-correct first calls
(evals/datasets/tool_tasks.jsonl):

  fine    35 fine-grained, one-endpoint-per-tool functions with terse descriptions
  coarse  4 coarse tools (marketplace_read / marketplace_write / portfolio / workspace) that take
          an ``action`` or ``resource`` argument
  best    the real deployed MCP surface (11 + 3 + 3 tools) with the rewritten descriptions
  (ablation) best_terse_descriptions: the same real tools with descriptions cut to a few words

Metrics per set: tool-selection accuracy, argument accuracy, tokens per task (tool schemas + task).

HONESTY: the selector is pluggable and the output states which one produced the numbers.
``offline-baseline`` is a deterministic keyword/regex router that runs with no model: its numbers
measure how LEXICALLY separable each tool set is, NOT how an LLM behaves; never quote them as an
LLM result. ``llm`` numbers come from a real chat model via ``LLMSelector``.

    python -m evals.runners.tool_design_eval                 # offline baseline (default)
    python -m evals.runners.tool_design_eval --selector llm  # needs a configured model (agent.llm)
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import math
import re
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
TASKS_PATH = ROOT / "evals" / "datasets" / "tool_tasks.jsonl"
OUT_PATH = ROOT / "evals" / "results" / "tool_design.json"
IGNORED_ARGS = {"idempotency_key", "trace_id", "portfolio_id"}


# ============================================================================ data types
@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]

    def for_prompt(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}


@dataclass
class Selection:
    tool: str | None
    args: dict[str, Any] = field(default_factory=dict)
    raw: str | None = None


@dataclass
class ToolSet:
    name: str
    tools: list[ToolSpec]
    translate: Callable[[dict[str, Any]], dict[str, Any]]   # task record -> gold {"tool","args"} for this set
    note: str = ""


class Selector(Protocol):
    kind: str   # "offline-baseline" | "llm"
    name: str

    async def select(self, task: str, tools: list[ToolSpec]) -> Selection: ...

    def describe(self) -> dict[str, Any]: ...


ChatFn = Callable[[str, str], "str | Awaitable[str]"]   # (system, user) -> assistant text


class LLMClient(Protocol):
    """Shape of ``agent.llm.LLM`` (it may not exist when this file is imported)."""

    async def chat(self, node: str, system: str, user: str, *, schema: Any = None, **kw: Any) -> Any: ...


# ============================================================================ tokens
def make_token_counter() -> tuple[Callable[[str], int], str]:
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s))), "tiktoken cl100k_base"
    except Exception:  # noqa: BLE001 - offline / not installed
        return (lambda s: math.ceil(len(s) / 4)), "approximation: ceil(characters / 4)"


def render_tools(tools: list[ToolSpec]) -> str:
    return json.dumps([t.for_prompt() for t in tools], separators=(",", ":"), ensure_ascii=False)


# ============================================================================ tool sets
def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


S, INT, N, B = {"type": "string"}, {"type": "integer"}, {"type": "number"}, {"type": "boolean"}
SL = {"type": "array", "items": S}


def _fine_tools() -> list[ToolSpec]:
    def t(name: str, desc: str, props: dict[str, Any] | None = None, req: list[str] | None = None) -> ToolSpec:
        return ToolSpec(name, desc, _obj(props or {}, req))

    return [
        t("search_jobs_by_keyword", "Search jobs by keyword.", {"query": S, "limit": INT}, ["query"]),
        t("search_jobs_by_category", "Search jobs by category.", {"category": S, "limit": INT}, ["category"]),
        t("search_jobs_by_skills", "Search jobs by skills.", {"skills": SL, "limit": INT}, ["skills"]),
        t("get_job_details", "Get job details.", {"job_id": S}, ["job_id"]),
        t("get_job_budget", "Get job budget.", {"job_id": S}, ["job_id"]),
        t("get_job_required_skills", "Get job skills.", {"job_id": S}, ["job_id"]),
        t("get_job_screening_questions", "Get job screening questions.", {"job_id": S}, ["job_id"]),
        t("get_client_profile", "Get client profile.", {"client_id": S}, ["client_id"]),
        t("get_client_payment_status", "Get client payment status.", {"client_id": S}, ["client_id"]),
        t("get_client_hire_rate", "Get client hire rate.", {"client_id": S}, ["client_id"]),
        t("get_client_past_jobs", "Get client past jobs.", {"client_id": S}, ["client_id"]),
        t("get_connects_balance", "Get Connects balance."),
        t("get_connects_weekly_allowance", "Get weekly Connects allowance."),
        t("get_market_price_stats", "Get market price stats.", {"category": S, "skills": SL}),
        t("get_market_hourly_stats", "Get market hourly stats.", {"category": S}),
        t("get_platform_rules", "Get platform rules."),
        t("get_connects_cost_per_proposal", "Get Connects cost per proposal."),
        t("list_threads", "List threads."),
        t("list_thread_messages", "List thread messages.", {"thread_id": S}, ["thread_id"]),
        t("list_events", "List events.", {"since": S}),
        t("preview_proposal_draft", "Preview proposal draft.",
          {"job_id": S, "cover_letter": S, "bid_amount": N, "idempotency_key": S}, ["job_id", "cover_letter", "bid_amount"]),
        t("create_proposal_draft", "Create proposal draft.",
          {"job_id": S, "cover_letter": S, "bid_amount": N, "idempotency_key": S}, ["job_id", "cover_letter", "bid_amount"]),
        t("preview_submit_proposal", "Preview proposal submission.", {"proposal_id": S, "idempotency_key": S},
          ["proposal_id"]),
        t("submit_proposal", "Submit proposal.", {"proposal_id": S, "idempotency_key": S}, ["proposal_id"]),
        t("preview_message", "Preview message.", {"thread_id": S, "body": S, "idempotency_key": S},
          ["thread_id", "body"]),
        t("send_message", "Send message.", {"thread_id": S, "body": S, "idempotency_key": S}, ["thread_id", "body"]),
        t("search_evidence", "Search evidence.", {"requirement": S, "k": INT}, ["requirement"]),
        t("search_evidence_by_outcome", "Search evidence by outcome.",
          {"requirement": S, "outcome": {"type": "string", "enum": ["won", "replied", "ignored"]}},
          ["requirement", "outcome"]),
        t("search_evidence_case_studies", "Search case studies.", {"requirement": S}, ["requirement"]),
        t("get_case_study", "Get case study.", {"id": S}, ["id"]),
        t("get_case_study_reviews", "Get case study reviews.", {"id": S}, ["id"]),
        t("list_skills", "List skills."),
        t("get_free_slots", "Get free slots.", {"days": INT, "duration_minutes": INT}),
        t("create_interview_hold", "Create interview hold.",
          {"slot": _obj({"start": S, "end": S}, ["start"]), "client": S, "job_id": S}, ["slot", "client"]),
        t("create_email_draft", "Create email draft.", {"to": S, "subject": S, "body": S}, ["to", "subject", "body"]),
    ]


def _coarse_tools() -> list[ToolSpec]:
    def e(*v: str) -> dict[str, Any]:
        return {"type": "string", "enum": list(v)}

    return [
        ToolSpec("marketplace_read", "Read marketplace data. Choose a resource.", _obj({
            "resource": e("jobs", "job", "client", "connects", "market_stats", "policy", "threads", "messages", "events"),
            "id": S, "query": S, "category": S, "skills": SL, "since": S, "limit": INT, "thread_id": S}, ["resource"])),
        ToolSpec("marketplace_write", "Write to the marketplace. Choose an action.", _obj({
            "action": e("draft_proposal", "submit_proposal", "send_message"), "job_id": S, "proposal_id": S,
            "thread_id": S, "cover_letter": S, "body": S, "bid_amount": N, "idempotency_key": S, "dry_run": B},
            ["action", "idempotency_key"])),
        ToolSpec("portfolio", "Access the portfolio. Choose an action.", _obj({
            "action": e("search_evidence", "case_study", "skills"), "requirement": S, "k": INT,
            "filters": _obj({"outcome": S, "types": SL}), "id": S}, ["action"])),
        ToolSpec("workspace", "Calendar and email. Choose an action.", _obj({
            "action": e("free_slots", "interview_hold", "email_draft"), "days": INT, "duration_minutes": INT,
            "slot": _obj({"start": S, "end": S}), "client": S, "job_id": S, "to": S, "subject": S, "body": S},
            ["action"])),
    ]


_TO_COARSE: dict[str, tuple[str, str, dict[str, str]]] = {
    # canonical tool -> (coarse tool, selector value, arg renames)
    "search_jobs": ("marketplace_read", "jobs", {}),
    "get_job": ("marketplace_read", "job", {"job_id": "id"}),
    "get_client_history": ("marketplace_read", "client", {"client_id": "id"}),
    "get_connects_balance": ("marketplace_read", "connects", {}),
    "get_market_stats": ("marketplace_read", "market_stats", {}),
    "get_platform_policy": ("marketplace_read", "policy", {}),
    "list_messages": ("marketplace_read", "messages", {}),
    "list_events": ("marketplace_read", "events", {}),
    "create_proposal_draft": ("marketplace_write", "draft_proposal", {}),
    "submit_proposal": ("marketplace_write", "submit_proposal", {}),
    "send_message": ("marketplace_write", "send_message", {}),
    "search_evidence": ("portfolio", "search_evidence", {}),
    "get_case_study": ("portfolio", "case_study", {}),
    "list_skills": ("portfolio", "skills", {}),
    "get_free_slots": ("workspace", "free_slots", {}),
    "create_interview_hold": ("workspace", "interview_hold", {}),
    "create_email_draft": ("workspace", "email_draft", {}),
}


def to_coarse(gold: dict[str, Any]) -> dict[str, Any]:
    tool, sel, rename = _TO_COARSE[gold["tool"]]
    args = {rename.get(k, k): v for k, v in gold["args"].items()}
    if gold["tool"] == "list_messages" and not args.get("thread_id"):
        sel = "threads"
    key = "resource" if tool == "marketplace_read" else "action"
    return {"tool": tool, "args": {key: sel, **args}}


def terse(spec: ToolSpec) -> ToolSpec:
    """Ablation: keep names and schemas, cut the description to the humanised name."""
    return ToolSpec(spec.name, spec.name.replace("_", " ").capitalize() + ".", spec.input_schema)


def build_sets(best_tools: list[ToolSpec]) -> list[ToolSet]:
    return [
        ToolSet("fine", _fine_tools(), lambda t: t.get("gold_fine") or t["gold"],
                "35 one-endpoint tools, terse descriptions"),
        ToolSet("coarse", _coarse_tools(), lambda t: to_coarse(t["gold"]),
                "4 action/resource-dispatch tools, generic descriptions"),
        ToolSet("best", best_tools, lambda t: t["gold"], "deployed MCP surface, rewritten descriptions"),
        ToolSet("best_terse_descriptions", [terse(t) for t in best_tools], lambda t: t["gold"],
                "ablation: deployed surface with one-line descriptions"),
    ]


async def load_best_tools() -> list[ToolSpec]:
    """The real tools, read from the real servers through an in-memory MCP client."""
    from types import SimpleNamespace

    from mcp.shared.memory import create_connected_server_and_client_session as connect

    from mcp_servers.marketplace import build_server as marketplace
    from mcp_servers.marketplace.service import MarketplaceConfig
    from mcp_servers.portfolio import build_server as portfolio
    from mcp_servers.workspace import WorkspaceConfig
    from mcp_servers.workspace import build_server as workspace

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        servers = [
            marketplace(MarketplaceConfig(adapter=SimpleNamespace(name="stub"), state_dir=Path(tmp) / "m")),
            portfolio(),
            workspace(WorkspaceConfig(store_path=Path(tmp) / "w.json")),
        ]
        specs: list[ToolSpec] = []
        for srv in servers:
            async with connect(srv) as c:
                for t in (await c.list_tools()).tools:
                    specs.append(ToolSpec(t.name, t.description or "", t.inputSchema))
        svc = getattr(servers[0], "_gigbid_service", None)
        if svc is not None:
            svc.idem.close()  # release the sqlite file before the temp dir is removed (Windows)
    return specs


# ============================================================================ scoring
_WORD = re.compile(r"[a-z0-9]+")


def _norm(s: str) -> str:
    return " ".join(_WORD.findall(s.lower()))


def values_match(gold: Any, pred: Any) -> bool:
    if isinstance(gold, dict):
        return isinstance(pred, dict) and all(k in pred and values_match(v, pred[k]) for k, v in gold.items())
    if isinstance(gold, list):
        return isinstance(pred, list) and sorted(map(_norm, map(str, gold))) == sorted(map(_norm, map(str, pred)))
    if isinstance(gold, bool) or isinstance(pred, bool):
        return gold is pred
    if isinstance(gold, (int, float)):
        try:
            return abs(float(gold) - float(pred)) < 1e-6
        except (TypeError, ValueError):
            return False
    if isinstance(gold, str):
        g, p = _norm(gold), _norm(str(pred))
        if len(g.split()) < 3:
            return g == p
        gt = set(g.split())
        return len(gt & set(p.split())) / len(gt) >= 0.6   # free text: containment, not exact string
    return gold == pred


def args_match(gold_args: dict[str, Any], pred_args: dict[str, Any]) -> bool:
    """Every gold argument must be present and right; extra optional arguments are not penalised."""
    return all(k in pred_args and values_match(v, pred_args[k])
               for k, v in gold_args.items() if k not in IGNORED_ARGS)


def score_task(gold: dict[str, Any], sel: Selection) -> dict[str, Any]:
    tool_ok = sel.tool == gold["tool"]
    args_ok = tool_ok and args_match(gold["args"], sel.args or {})
    return {"tool_ok": tool_ok, "args_ok": args_ok}


# ============================================================================ selectors
class LLMSelector:
    """LLM-backed router: gives the model the tool list and the task, parses a JSON tool call."""

    kind = "llm"

    def __init__(self, chat: ChatFn, name: str = "llm", model: str | None = None) -> None:
        self.chat, self.name, self.model = chat, name, model

    SYSTEM = (
        "You route requests for a freelancer copilot to tools. Available tools (JSON):\n{tools}\n\n"
        'Reply with ONLY a JSON object {{"tool": "<name>", "args": {{...}}}} for the single best FIRST call. '
        "Use only argument names from the tool's input_schema and omit optional arguments the request "
        "does not mention."
    )

    async def select(self, task: str, tools: list[ToolSpec]) -> Selection:
        out = self.chat(self.SYSTEM.format(tools=render_tools(tools)), task)
        text = await out if inspect.isawaitable(out) else out
        return parse_selection(str(text))

    def describe(self) -> dict[str, Any]:
        return {"selector": "llm", "selector_name": self.name, "model": self.model}


def parse_selection(text: str) -> Selection:
    m = re.search(r"\{.*\}", re.sub(r"```(?:json)?", "", text), re.S)
    if not m:
        return Selection(None, {}, text[:200])
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return Selection(None, {}, text[:200])
    args = d.get("args") or d.get("arguments") or {}
    return Selection(d.get("tool") or d.get("name"), args if isinstance(args, dict) else {}, text[:200])


def llm_client_chat_fn(llm: LLMClient, node: str = "scout") -> tuple[ChatFn, Callable[[], str | None]]:
    """Adapt ``agent.llm.LLM`` to a chat function. Refuses stub output so a stub can never be
    reported as an LLM result."""
    seen: list[str] = []

    async def chat(system: str, user: str) -> str:
        res = await llm.chat(node, system, user, use_cache=False)
        if getattr(res, "stub", False):
            raise RuntimeError("LLM provider is 'stub'/unavailable: refusing to label stub output as an LLM result")
        seen.append(getattr(res, "model", ""))
        return res.text

    return chat, lambda: seen[0] if seen else None


_STOP = set("a an the and or of to in on for with by is are was were be as at from that this it its our we you "
            "your i my me do does did have has had not but if then than so can will would should could what "
            "which how when who whose any all up into over about me show give get find".split())
_SKILL_VOCAB = ["Python", "FastAPI", "SQL", "scikit-learn", "React", "TypeScript", "Docker", "PyTorch", "Django"]
_ID_RE = re.compile(r"\b[A-Za-z]{1,6}-[A-Za-z0-9][A-Za-z0-9\-]*\b")
_ID_PREFIX = {"job_id": "job-", "client_id": "cl-", "thread_id": "th-", "proposal_id": "p-"}


def _toks(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower().replace("_", " ")):
        if w in _STOP:
            continue
        out.append(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def _schema_type(p: dict[str, Any]) -> str | None:
    if "type" in p:
        return p["type"]
    for alt in p.get("anyOf", []):
        if alt.get("type") not in (None, "null"):
            return alt["type"]
    return None


def _enum_of(p: dict[str, Any]) -> list[str] | None:
    if "enum" in p:
        return p["enum"]
    for alt in p.get("anyOf", []):
        if "enum" in alt:
            return alt["enum"]
    return None


class OfflineBaselineSelector:
    """Deterministic, model-free router: IDF-weighted keyword overlap picks the tool (name counts
    double, description and parameter names count once); regexes fill the arguments from the schema.
    It exists so the harness runs offline and in CI. It is NOT an LLM and says so in the output."""

    kind = "offline-baseline"
    name = "keyword-overlap + regex args (no model)"

    async def select(self, task: str, tools: list[ToolSpec]) -> Selection:
        docs = []
        for t in tools:
            props = t.input_schema.get("properties", {})
            enums = " ".join(" ".join(_enum_of(p) or []) for p in props.values())
            docs.append(Counter(_toks(t.name) * 2 + _toks(t.description) + _toks(" ".join(props)) + _toks(enums)))
        df: Counter[str] = Counter()
        for d in docs:
            df.update(d.keys())
        q = set(_toks(task))
        n = len(tools)
        scores = [sum(math.log(1 + n / df[w]) * (1 + math.log(d[w])) for w in q if w in d) for d in docs]
        best = max(range(n), key=lambda i: (scores[i], -i))
        spec = tools[best]
        return Selection(spec.name, self.extract_args(task, spec))

    def describe(self) -> dict[str, Any]:
        return {"selector": "offline-baseline", "selector_name": self.name, "model": None}

    @staticmethod
    def extract_args(task: str, spec: ToolSpec) -> dict[str, Any]:
        props = spec.input_schema.get("properties", {})
        ids = _ID_RE.findall(task)
        quoted = [a or b for a, b in re.findall(r"'([^']+)'|\"([^\"]+)\"", task)]
        out: dict[str, Any] = {}
        for name, p in props.items():
            if name in IGNORED_ARGS:
                continue
            v: Any = None
            typ, enum = _schema_type(p), _enum_of(p)
            if name.endswith("_id") or name == "id":
                pref = _ID_PREFIX.get(name)   # generic `id` (coarse tools, case studies): first id found
                v = next((i for i in ids if pref and i.lower().startswith(pref)), ids[0] if ids else None)
            elif enum:
                tw = set(_toks(task))
                sc = [(len(tw & set(_toks(e))), -k) for k, e in enumerate(enum)]
                v = enum[max(range(len(enum)), key=lambda k: sc[k])] if max(sc)[0] > 0 else None
            elif name == "dry_run":
                v = True if re.search(r"preview|dry run|would cost|without send", task, re.I) else None
            elif name in ("limit", "k"):
                m = re.search(r"(?:up to|top|first|at most)\s+(\d+)", task, re.I)
                v = int(m.group(1)) if m else None
            elif name == "days":
                m = re.search(r"(\d+)\s*days?", task, re.I)
                v = int(m.group(1)) if m else None
            elif name == "duration_minutes":
                m = re.search(r"(\d+)[\s-]*minute", task, re.I)
                v = int(m.group(1)) if m else None
            elif name == "bid_amount":
                m = re.search(r"bid(?: of)?\s+(\d+)|(\d+)\s*(?:dollars|usd)", task, re.I)
                v = float(m.group(1) or m.group(2)) if m else None
            elif name == "since":
                m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", task) or re.search(r"event\s+(\d+)", task, re.I)
                v = m.group(1) if m else None
            elif name == "skills":
                found = [s for s in _SKILL_VOCAB if re.search(rf"\b{re.escape(s)}\b", task)]
                v = found or None
            elif name == "category":
                m = re.search(r"\b([a-z]+_[a-z]+)\b", task)
                v = m.group(1) if m else None
            elif name == "to":
                m = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", task)
                v = m.group(0) if m else None
            elif name == "client":
                m = re.search(r"\bwith ([A-Z][a-z]+)", task)
                v = m.group(1) if m else None
            elif name in ("cover_letter", "body"):
                v = quoted[-1] if quoted else None
            elif name == "subject":
                v = quoted[0] if quoted else None
            elif name in ("query", "requirement"):
                v = quoted[0] if quoted else _phrase_after(task)
            elif name == "slot" and typ == "object":
                m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", task)
                v = {"start": m.group(0)} if m else None
            elif name == "filters" and typ == "object":
                f: dict[str, Any] = {}
                m = re.search(r"\b(won|replied|ignored)\b", task, re.I)
                if m:
                    f["outcome"] = m.group(1).lower()
                if re.search(r"case stud", task, re.I):
                    f["types"] = ["case_study"]
                elif re.search(r"proposal", task, re.I):
                    f["types"] = ["proposal"]
                v = f or None
            if v is not None:
                out[name] = v
        return out


def _phrase_after(task: str) -> str | None:
    ms = list(re.finditer(r"(?:that i have|mentions?|matching|about|for)\s+(.+?)[.?!]*$", task, re.I))
    return ms[-1].group(1).strip() if ms else None


# ============================================================================ harness
def load_tasks(path: Path = TASKS_PATH) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


async def evaluate_set(selector: Selector, ts: ToolSet, tasks: list[dict[str, Any]],
                       count_tokens: Callable[[str], int]) -> dict[str, Any]:
    schema_tokens = count_tokens(render_tools(ts.tools))
    rows, tok_total = [], 0
    for task in tasks:
        gold = ts.translate(task)
        try:
            sel = await selector.select(task["task"], ts.tools)
            err = None
        except Exception as exc:  # noqa: BLE001 - a failing model call is a wrong answer, recorded
            sel, err = Selection(None, {}), f"{type(exc).__name__}: {str(exc)[:120]}"
        sc = score_task(gold, sel)
        tokens = schema_tokens + count_tokens(task["task"])
        tok_total += tokens
        rows.append({"id": task["id"], "gold_tool": gold["tool"], "pred_tool": sel.tool, **sc,
                     "tokens": tokens, **({"error": err} if err else {})})
    n = len(rows)
    right_tool = [r for r in rows if r["tool_ok"]]
    return {
        "description": ts.note,
        "n_tools": len(ts.tools),
        "schema_tokens": schema_tokens,
        "n_tasks": n,
        "tool_selection_accuracy": round(len(right_tool) / n, 4),
        "argument_accuracy": round(sum(r["args_ok"] for r in rows) / n, 4),
        "argument_accuracy_given_correct_tool": round(
            sum(r["args_ok"] for r in right_tool) / len(right_tool), 4) if right_tool else 0.0,
        "tokens_per_task": round(tok_total / n, 1),
        "per_task": rows,
    }


async def run_eval(selector: Selector, tasks: list[dict[str, Any]] | None = None,
                   sets: list[ToolSet] | None = None) -> dict[str, Any]:
    tasks = tasks if tasks is not None else load_tasks()
    sets = sets if sets is not None else build_sets(await load_best_tools())
    count_tokens, method = make_token_counter()
    out_sets = {ts.name: await evaluate_set(selector, ts, tasks, count_tokens) for ts in sets}
    meta = {
        **selector.describe(),
        "n_tasks": len(tasks),
        "tokens_per_task": f"tokens of the rendered tool schemas (name, description, input_schema) + the task text; {method}",
        "arg_scoring": "gold args must be present and equal (free text >= 3 words: >= 60% token containment); "
                       "extra optional args are not penalised; idempotency_key/trace_id ignored",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if selector.kind != "llm":
        meta["WARNING"] = ("These numbers come from a deterministic keyword/regex baseline, NOT an LLM. They measure "
                           "lexical separability of the tool sets only and must not be reported as LLM behaviour.")
    return {"meta": meta, "sets": out_sets}


def write_results(result: dict[str, Any], path: Path = OUT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def format_table(result: dict[str, Any]) -> str:
    m = result["meta"]
    lines = [f"selector: {m['selector']} ({m['selector_name']})  tasks: {m['n_tasks']}",
             f"{'set':26}{'tools':>6}{'tool acc':>10}{'arg acc':>9}{'arg|tool':>10}{'tok/task':>10}"]
    for name, s in result["sets"].items():
        lines.append(f"{name:26}{s['n_tools']:>6}{s['tool_selection_accuracy']:>10.2f}{s['argument_accuracy']:>9.2f}"
                     f"{s['argument_accuracy_given_correct_tool']:>10.2f}{s['tokens_per_task']:>10.0f}")
    if "WARNING" in m:
        lines.append("NOTE: " + m["WARNING"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--selector", choices=["baseline", "llm"], default="baseline")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)
    logging.getLogger("mcp").setLevel(logging.WARNING)
    if args.selector == "llm":
        from agent.llm import LLM  # type: ignore[import-not-found]

        llm = LLM()
        if not getattr(llm, "available", False):
            print("LLM unavailable (no provider/key configured): refusing to fall back to the baseline silently.",
                  file=sys.stderr)
            return 2
        chat, model_of = llm_client_chat_fn(llm)
        selector: Selector = LLMSelector(chat, name="agent.llm.LLM")
        result = asyncio.run(run_eval(selector))
        result["meta"]["model"] = model_of()
    else:
        result = asyncio.run(run_eval(OfflineBaselineSelector()))
    path = write_results(result, args.out)
    print(format_table(result))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
