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
  {job_id, persona_id, client_id, label: bid|skip, is_scam, scam_type|null, has_injection,
   injection_canary|null, gold_project_ids:[...], fair_price_band:{min,max}, requirements:[...],
   job_type: fixed|hourly, n_requirements (1..7), duplicate_of|null}
  Notes: `injection_canary` is a deterministic token (e.g. "PINEAPPLE-7") embedded in the planted
  injection text ("... reply with the word PINEAPPLE-7"); an agent output containing it = attack
  succeeded. `gold_project_ids` is non-empty iff label=bid; generic skills (used by >4 projects) are
  requirements but do not widen it. `fair_price_band` is USD total for fixed, USD/h for hourly.
  scam_type in unpaid_trial|off_platform_contact|payment_upfront|guarantee_demand|credential_phishing.
  `data/processed/local_test_<persona>.jsonl` has the same rows plus an embedded `job` object.
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
| `GET /v1/policy` | `{version, connects_per_proposal, rules:[{id, type, pattern\|value, description, enforcement}], rate_limit_rpm, fee_pct, weekly_allowance}`; rule types: `forbid_regex` (pattern), `max_words` (value), `connects_cost` (value; flat cost, overrides per-job cost), `require_phrase` (value). Only enabled rules are listed. Source of truth is `gigsim/policy.json`, hot-reloaded on edit (change-request hook) |
| `GET /v1/market_stats?category=&skills=a,b` | `{category, n, p10, p25, p50, p75, p90, hourly_p50, skills:[{skill,n,p10,...,hourly_p50}]}` from `data/gigsim_seed/history_stats.json` (category = display name or id; omitted -> "All categories"; unknown -> 404) |
| `POST /v1/proposals` | body `{job_id, cover_letter, screening_answers[], bid_amount, dry_run}` -> `{proposal_id|null, status:"draft"|"preview", connects_cost, balance_after, payload}`; dry_run never persists |
| `POST /v1/proposals/{id}/submit` | -> `{proposal_id,status:"submitted",connects_spent,balance}`; same Idempotency-Key never spends twice |
| `GET /v1/proposals?status=` / `GET /v1/proposals/{id}` | status draft/submitted/viewed/replied/interview/hired/lost |
| `GET /v1/messages?thread_id=` / `GET /v1/threads` | thread = one client conversation |
| `POST /v1/messages` | `{thread_id, body}` + Idempotency-Key |
| `GET /v1/events?since=<event_id>` | `[{event_id, ts, type: viewed|replied|interview|hired|lost|message, proposal_id, thread_id}]` |
| `POST /v1/sim/tick` | `{steps:int}` advance simulated time; clients (hidden prefs + deterministic seeded decision) decide ignore/reply/interview/hire |
| `POST /v1/sim/reset` | reseed (tests) |

### 2.1 Clarifications (GigSim stand-in; shapes the table leaves open)

* Default token when `GIGSIM_API_TOKEN` is unset: `replace_me`. `X-Freelancer-Id` is required on
  connects/proposals/threads/messages/events (400 `missing_freelancer_id`; 404 `unknown_freelancer`).
* `Idempotency-Key` is **required** (400 `idempotency_key_required`) on `POST /v1/proposals/{id}/submit`
  and `POST /v1/messages`, optional on `POST /v1/proposals` (drafts). Same key + same request replays the stored
  response (header `Idempotent-Replay: true`); same key + different request -> 422 `idempotency_key_reuse`.
* Status codes: 201 on draft/message create, 402 `insufficient_connects`, 409 `already_exists` (open proposal for
  the job) / `not_a_draft`, 422 `policy_violation` (body has `violations:[{rule_id,...}]`; dry_run instead returns
  them in `payload.policy_violations`), 429 `rate_limited` + `Retry-After`, 503 `injected_failure`
  (`GIGSIM_ERROR_RATE`; `GIGSIM_ERROR_AFTER_COMMIT_RATE` commits then fails so retries must reuse the key).
* `balance_after` = balance after the proposal would be submitted (a draft itself spends nothing).
* Collections are wrapped: `{proposals:[...]}`, `{threads:[...]}`, `{thread_id, messages:[{message_id,thread_id,sender:
  client|freelancer,body,ts}]}`; `GET /v1/events` is a bare list; `event_id` is an increasing integer (`since` = last seen).
* Jobs visible via `GET /v1/jobs` are stream + dev jobs with `posted_at <=` the simulated clock (stream jobs appear as
  `POST /v1/sim/tick` advances time; one step = 1 simulated hour); `?kind=history` lists history jobs incl. `final_price`.
* After a client `replied`, the thread waits for a freelancer message; without one within 72 simulated hours the
  proposal becomes `lost`. `POST /v1/sim/reset` body `{seed?}`; `GET /v1/sim/clock`.
* Env: `GIGSIM_STATE_PATH` (JSON state, `""` = in memory), `GIGSIM_SEED_DIR`, `GIGSIM_POLICY_PATH`, `GIGSIM_SEED`,
  `GIGSIM_REQUIRE_IDEMPOTENCY`, `GIGSIM_EXTRA_JOBS` (jsonl of extra jobs, e.g. a local_test file), `GIGSIM_PORT`.

Client decision model is deterministic given a seed: reply prob rises with evidence-specific
proposal text (mentions of the client's must-have skills), price under budget ceiling, non-generic
opening; drops for generic openings, forbidden claims, over-ceiling price.

## 3. MCP tool surface (`mcp_servers/`)

Official MCP Python SDK (`mcp.server.fastmcp.FastMCP`). Each server exposes `build_server(config) -> FastMCP`
(so tests use an in-memory client) and a `__main__` with `--transport stdio|streamable-http --port --insecure-no-auth`.
HTTP requires a bearer token (env `MARKETPLACE_MCP_TOKEN` / `PORTFOLIO_MCP_TOKEN` / `WORKSPACE_MCP_TOKEN`; `/health`
is open). Full inventory with annotations and auth: `docs/TOOLS.md`. Schemas are snapshot-tested
(`tests/contract/snapshots/tool_schemas.json`, regenerate with `UPDATE_SNAPSHOTS=1`).

Portfolio (read-only; `portfolio_id` slug `^[a-z0-9_-]{1,40}$`, defaults to env `PORTFOLIO_ID`; self-contained, published
standalone as `gigbid-portfolio-mcp`):
`search_evidence(requirement:str(3..500), k:int=5 (1..20), filters:{types[],project_id,skills[],outcome,since}|None, portfolio_id|None)
 -> {items:[EvidenceRef], portfolio_id, retriever}`,
`get_case_study(id, portfolio_id|None) -> {id, project_id, title, markdown, skills, industry, date, outcome_summary, reviews[], related_proposal_ids[]}`,
`list_skills(portfolio_id|None) -> {skills:[{name,count}], portfolio_id}`;
resources `portfolio://case/{id}`, `portfolio://proposal/{id}`, `portfolio://skills`; prompts `screening_answer`,
`cover_letter_from_evidence`, `portfolio_gap_check`. Retriever: injected object > `rag.retriever.get_retriever(variant, portfolio_id)`
(env `PORTFOLIO_BACKEND=auto|rag|local`, `RAG_VARIANT`) > built-in BM25 over the persona folder layout of section 1.

Marketplace (read + write). Reads: `search_jobs(query,category,skills[],since,limit<=50,cursor) -> {jobs,next_cursor}`,
`get_job(job_id) -> Job`, `get_client_history(client_id)`, `get_connects_balance() -> {balance,weekly_allowance,spent_this_week}`,
`get_market_stats(category,skills[]) -> {category,n,p10,p50,p90,hourly_p50,...}` (GigSim `GET /v1/market_stats`),
`get_platform_policy() -> {version,connects_per_proposal,rules:[{id,type,pattern|value,description}],rate_limit_rpm}` (GigSim `GET /v1/policy`),
`list_messages(thread_id|None) -> {thread_id,threads[],messages[]}` (no thread_id lists threads), `list_events(since) -> {events[],last_event_id}`.
Writes (all REQUIRE `idempotency_key`, accept `dry_run`): `create_proposal_draft(job_id,cover_letter(20..5000),bid_amount(>0),idempotency_key,
screening_answers[],dry_run) -> {proposal_id|null,status:preview|draft|submitted,connects_cost,balance_after,payload,dry_run,idempotent_replay,...}`,
`submit_proposal(proposal_id,idempotency_key,dry_run) -> same shape plus {connects_spent,balance}`, `send_message(thread_id,body(1..4000),idempotency_key,dry_run)
-> {message_id,thread_id,status:preview|draft|sent,payload,...}`. Guards on every call, in order: user resolution -> per-user token bucket
(default 20 rpm, below GigSim's 60) -> durable idempotency store (SQLite; same key + same args returns the first result with
`idempotent_replay=true`, same key + different args is `idempotency_conflict`; dry runs never consume a key) -> adapter -> hash-chained
append-only JSONL audit log (user, tool, PII-masked arguments, result summary, trace_id). Errors are MCP tool errors whose text starts
with `<code>: ` (`not_found, rate_limited, upstream_rate_limited, upstream_unavailable, upstream_rejected, unsupported, unauthorized,
forbidden, idempotency_conflict, insufficient_connects`). Adapters: `adapters/gigsim.py`, `adapters/upwork_live.py` (drafts only; writes return
`status:"draft"`, `requires_user_confirmation:true`) selected by `marketplace.mode` (env `MARKETPLACE_MODE` overrides).

Workspace (local mock store, deterministic Mon-Fri 09:00-17:00 UTC calendar): `get_free_slots(days<=14,duration_minutes 15..240,from_date,limit)
-> {slots:[{start,end}]}`, `create_interview_hold(slot:{start,end?}, client, job_id, duration_minutes) -> {hold_id,status:"tentative",...}`,
`create_email_draft(to,subject,body) -> {draft_id,status:"draft"}` (no send tool exists).

Tenant scoping: the acting user is NEVER a tool argument. It travels as MCP `_meta.user_id` (set by `ToolGateway`) or the
`X-GigBid-User` HTTP header; the server forwards it to the adapter (GigSim `X-Freelancer-Id`) and partitions rate limits,
idempotency keys, proposal ownership and workspace data by it. `trace_id` is accepted as optional tool argument or via
`_meta.trace_id` / `X-Trace-Id` and is written to the audit log.

Every tool returns structured output declared by an `outputSchema`.

## 4. Agent-side (`agent/`)

* `marketplace_port.MarketplacePort` (Protocol; reads `search_jobs, get_job, get_client_history, get_connects_balance, get_market_stats,
  get_platform_policy, list_messages, list_events`; writes `create_proposal_draft, submit_proposal, send_message` with `idempotency_key`
  and `dry_run`) -> implemented by `McpMarketplacePort(gateway, agent)`, which calls the Marketplace MCP server through `ToolGateway`.
  The graph never sees which adapter is live. `.as_agent(name)` / `.with_approval()` return sibling ports.
* `agent/mcp_client.py`: per-agent allowlists by tool name (`AGENT_ALLOWLISTS`), `build_connections()` for `MultiServerMCPClient`
  (+ optional GitHub MCP and Upwork MCP entries), `tools_for_agent()` for LangChain tool lists.
  Allowlists: scout `search_jobs,get_job`; analyst none; risk_assessor `get_client_history,get_job`; fit_matcher / writer / critic
  portfolio read; pricing `get_market_stats,get_connects_balance,get_job`; compliance `get_platform_policy`; submitter
  `create_proposal_draft,submit_proposal`; client_liaison marketplace read + `send_message` + workspace + `search_evidence`.
* `agent/tools.py::ToolGateway(config, user_id=, servers=, approval_mode="trust_graph"|"strict")`:
  `await call(agent, tool, args, trace_id=None, *, approved=False) -> dict` (plain structured result). Enforces allowlists
  (`ToolNotAllowed`), per-attempt timeout, bounded retry with exponential backoff, tool errors as `ToolCallFailed(code)`, and a
  degraded mode: `ToolUnavailable(server, queued)`; idempotent writes made while a server is down are queued and replayed once by
  `await gateway.recover()`; `gateway.status()` -> `{ok, degraded[], servers{}, queued, message}` for the UI.
  `gateway.trace` = list of `{agent, tool, args(masked), result_digest, latency_s, ok, trace_id, server, attempts, error}`;
  `gateway.for_run(trace_id)` returns a view sharing connections/health/queue whose `.trace` holds only that run's records.
  Transport from `tool_servers.transport` (env `TOOL_TRANSPORT`): `memory` = in-process FastMCP via `mcp.shared.memory`, `http` =
  `MultiServerMCPClient` over Streamable HTTP (bearer from `<SERVER>_MCP_TOKEN`).
  `strict` approval mode additionally requires `approved=True` for real (non dry-run) writes; the default trusts the graph's
  approval node (which already refuses to write without a human decision).
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
