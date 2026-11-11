# Interfaces (contract between modules)

Single source of truth for how the parts talk. Code should match this; change this file in the same
commit as any interface change.

Python import roots are the repo root: `agent`, `rag`, `mcp_servers`, `gigsim`, `apps.api`, `worker`, `evals`.
Python >= 3.11, no code may assume 3.14. Tests: `pytest -q` from repo root. Style: ruff, line length 100.

## 1. Personas and data (`data/`)

Persona ids: `ai_ml`, `fullstack`, `data_analyst`. Generated deterministically (seeded) by
`python -m gigsim.datagen` into:

```
data/personas/<persona_id>/
  profile.json            {persona_id, display_name, headline, skills[], hourly_rate_usd,
                           min_project_budget_usd, availability_hours_per_week,
                           weekly_connects_budget, saved_searches:[{name, query, category?}]}
  cv.md  cv.pdf
  case_studies/<project_id>.md       front-matter-free markdown, first line "# Title"
  repos/<project_id>/README.md  + repos/<project_id>/src/*.py|ts|sql   (code snippets)
  reviews.json            [{review_id, project_id, client_industry, rating, text, date}]
  proposals.json          [{proposal_id, job_title, text, outcome: won|replied|ignored, date,
                            project_ids:[...], client_industry, category}]    ~150 each
  projects.json           canonical fact sheet per project (the generator's source of truth):
                          [{project_id, title, skills[], industry, date, outcome_summary, aliases[]}]
data/gigsim_seed/
  jobs.jsonl              all jobs GigSim serves (history ~1500 w/ final_price, stream jobs, dev jobs)
  clients.jsonl           client profiles + public history (hidden prefs live only inside gigsim/)
  history_stats.json      pricing stats per category/skill: {category: {n, p10, p50, p90, hourly_p50}}
data/policy_pack/marketplace_policy.md   (provided; do not edit)
evals/datasets/dev_<persona_id>.jsonl    ~200 jobs/persona gold labels, one JSON per line:
  {job_id, persona_id, label: bid|skip, is_scam, scam_type|null, has_injection,
   gold_project_ids:[...], fair_price_band:{min,max}, requirements:[...], job_type, n_requirements,
   duplicate_of|null}
data/processed/             generated, git-ignored (chunks, indexes, a local stand-in "hidden" test set)
```

Job object (GigSim `Job`):
`{job_id, client_id, title, description, category, required_skills[], budget:{type,min,max,currency},
  duration_days, screening_questions[], posted_at(ISO), connects_cost}`.
Gold retrieval is **project-level**: a retrieved chunk counts via its `project_id`.

## 2. GigSim REST (`gigsim/`, port 8081)

Auth: `Authorization: Bearer $GIGSIM_API_TOKEN`; acting freelancer: header `X-Freelancer-Id: <persona_id>`.
`Idempotency-Key` header on every POST that spends or sends. Errors: JSON `{error, detail}`;
429 carries `Retry-After`; env `GIGSIM_ERROR_RATE` injects 5xx; `GIGSIM_RATE_LIMIT_RPM` (default 60).

| Method + path | Notes |
|---|---|
| `GET /health` | `{status:"ok"}` |
| `GET /v1/jobs?q=&category=&skills=a,b&since=ISO&limit=50&cursor=` | `{jobs:[Job], next_cursor}` |
| `GET /v1/jobs/{job_id}` | `Job` |
| `GET /v1/clients/{client_id}` | `{client_id,name,industry,payment_verified,total_spent,hire_rate,avg_rating,jobs_posted,member_since,country,history:[{job_id,title,outcome,paid,feedback}]}` |
| `GET /v1/connects` | `{balance, weekly_allowance, spent_this_week}` |
| `GET /v1/policy` | `{version, connects_per_proposal, rules:[...], rate_limit_rpm}` (change-request hook) |
| `POST /v1/proposals` | body `{job_id, cover_letter, screening_answers[], bid_amount, dry_run}` -> `{proposal_id|null, status:"draft"|"preview", connects_cost, balance_after, payload}`; dry_run never persists |
| `POST /v1/proposals/{id}/submit` | -> `{proposal_id,status:"submitted",connects_spent,balance}`; same Idempotency-Key never spends twice |
| `GET /v1/proposals?status=` / `GET /v1/proposals/{id}` | status draft/submitted/viewed/replied/interview/hired/lost |
| `GET /v1/messages?thread_id=` / `GET /v1/threads` | thread = one client conversation |
| `POST /v1/messages` | `{thread_id, body}` + Idempotency-Key |
| `GET /v1/events?since=<event_id>` | `[{event_id, ts, type: viewed|replied|interview|hired|lost|message, proposal_id, thread_id}]` |
| `POST /v1/sim/tick` | `{steps:int}` advance simulated time; clients (hidden prefs + deterministic seeded decision) decide ignore/reply/interview/hire |
| `POST /v1/sim/reset` | reseed (tests) |

Client decision model is deterministic given a seed: reply prob rises with evidence-specific
proposal text (mentions of the client's must-have skills), price under budget ceiling, non-generic
opening; drops for generic openings, forbidden claims, over-ceiling price.

## 3. MCP tool surface (`mcp_servers/`)

Official MCP Python SDK (`mcp.server.fastmcp.FastMCP`). Each server exposes `build_server(config) -> FastMCP`
(so tests use an in-memory client) and a `__main__` with `--transport stdio|streamable-http --port`.

Portfolio (read-only; `portfolio_id` defaults to env `PORTFOLIO_ID`):
`search_evidence(requirement:str, k:int=5, filters:dict|None, portfolio_id|None) -> {items:[EvidenceRef]}`,
`get_case_study(id) -> {...}`, `list_skills() -> {skills:[{name,count}]}`;
resources `portfolio://case/{id}`, `portfolio://proposal/{id}`; prompts such as `screening_answer`.
Backed by `rag.retriever.get_retriever(...)`.

Marketplace (read + write; HTTP needs bearer): read `search_jobs, get_job, get_client_history,
get_connects_balance, list_messages, list_events`; write `create_proposal_draft, submit_proposal,
send_message` (all take `idempotency_key`, `dry_run`; audit log JSONL append-only; rate limiter).
Adapters: `adapters/gigsim.py`, `adapters/upwork_live.py` selected by `marketplace.mode`.

Workspace: `get_free_slots(days, duration_minutes)`, `create_interview_hold(slot, client, job_id)`,
`create_email_draft(to, subject, body)` (local mock store).

Every tool returns JSON-serialisable structured output. `trace_id` is accepted as optional arg or
via MCP `_meta` and is written to the audit log.

## 4. Agent-side (`agent/`)

* `marketplace_port.MarketplacePort` (Protocol) -> implemented by `McpMarketplacePort`, which calls the
  Marketplace MCP server. The graph never sees which adapter is live.
* `agent/tools.py::ToolGateway.call(agent, tool, args)` enforces per-agent allowlists, timeouts,
  bounded retry+backoff and a degraded mode (`ToolUnavailable`).
* `agent/llm.py::LLM.chat(node, system, user, *, schema=None) -> LLMResult` picks model per node from
  config, falls back, counts tokens/cost, masks PII in logs. Provider `stub` = deterministic offline.
* `rag.retriever.get_retriever(variant, portfolio_id) -> Retriever` with
  `search(requirement, k=5, filters=None) -> list[EvidenceRef-like dict]` and
  `search_job(job_spec_dict, k=5) -> list[dict]`. Variants in `rag/variants/vN_*.py`, each exposing
  `build(index, cfg) -> Retriever`-compatible object (see rag/variants/README.md).

## 5. API (`apps/api`, prefix `/api`, bearer session token)

OpenAPI is the contract for the web client (`apps/web/src/lib/api` is generated by `npm run gen:api`).
Routes: auth (`/auth/register|login|me`), onboarding/portfolio, jobs (`/jobs`, `/jobs/{id}`,
`/jobs/{id}/analyze`, `/jobs/{id}/skip`), proposals (`/proposals/{job_id}`), approvals
(`/approvals`, `/approvals/{id}/decision`), pipeline, messages/threads, runs (`/runs`, `/runs/{id}`,
`/runs/{id}/stream` SSE, `/runs/{id}/trace`), analytics, settings, memory (`/memory`, `DELETE /memory/{id}`),
`/health` (includes `marketplace.ok`). Every response carries `X-Trace-Id`.
