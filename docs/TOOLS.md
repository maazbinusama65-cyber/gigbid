# MCP Tool Inventory

Agents never call GigSim, Upwork, a database or a file directly: every capability below is an MCP tool
with a schema, an owner and a test. Contract details: `docs/INTERFACES.md` section 3-4. Schemas are
snapshot-tested (`tests/contract/snapshots/tool_schemas.json`).

Annotation legend: **RO** `readOnlyHint`, **D** `destructiveHint`, **I** `idempotentHint`, **OW** `openWorldHint`
(talks to a system we do not control). A tick means the hint is `true`; a dash means `false`.

## Own servers

| Tool | Server | Read / write | RO | D | I | OW | Auth |
|---|---|---|---|---|---|---|---|
| `search_evidence` | portfolio | read | yes | - | yes | - | stdio: none; HTTP: bearer `PORTFOLIO_MCP_TOKEN` |
| `get_case_study` | portfolio | read | yes | - | yes | - | same |
| `list_skills` | portfolio | read | yes | - | yes | - | same |
| `search_jobs` | marketplace | read | yes | - | yes | yes | HTTP: bearer `MARKETPLACE_MCP_TOKEN`; upstream: `GIGSIM_API_TOKEN` or per-user Upwork OAuth |
| `get_job` | marketplace | read | yes | - | yes | yes | same |
| `get_client_history` | marketplace | read | yes | - | yes | yes | same |
| `get_connects_balance` | marketplace | read | yes | - | yes | yes | same |
| `get_market_stats` | marketplace | read | yes | - | yes | yes | same (unsupported in live mode) |
| `get_platform_policy` | marketplace | read | yes | - | yes | yes | same |
| `list_messages` | marketplace | read | yes | - | yes | yes | same |
| `list_events` | marketplace | read | yes | - | yes | yes | same (unsupported in live mode unless the Upwork tool map defines it) |
| `create_proposal_draft` | marketplace | **write** (draft, spends nothing) | - | - | yes (key) | yes | same + `idempotency_key` required |
| `submit_proposal` | marketplace | **write** (spends Connects, irreversible) | - | yes | yes (key) | yes | same + `idempotency_key` required; live mode never submits |
| `send_message` | marketplace | **write** (client sees it, irreversible) | - | yes | yes (key) | yes | same + `idempotency_key` required; live mode saves a draft only |
| `get_free_slots` | workspace | read | yes | - | yes | - | stdio: none; HTTP: bearer `WORKSPACE_MCP_TOKEN` |
| `create_interview_hold` | workspace | write (tentative hold) | - | - | yes | - | same |
| `create_email_draft` | workspace | write (draft only; no send tool exists) | - | - | yes | - | same |

Why `submit_proposal` and `send_message` are `destructiveHint=true` while `create_proposal_draft` is not: a draft
is reversible and additive; a submitted proposal spends Connects and a sent message cannot be recalled.

Portfolio also exposes resource templates `portfolio://case/{id}`, `portfolio://proposal/{id}`, a `portfolio://skills`
resource, and prompts `screening_answer`, `cover_letter_from_evidence`, `portfolio_gap_check`.

### Server-side guards (marketplace, every call)

* Bearer auth on the HTTP endpoint (constant-time compare, token from env, `/health` open, refuses to start without a token).
* Per-user token bucket (default 20 requests/minute, burst 5 per `marketplace.max_requests_per_minute`), deliberately under
  GigSim's 60 rpm.
* Idempotency key required on every write; durable SQLite dedupe (survives restart); same key with different arguments is
  rejected; `dry_run` returns the exact payload and Connects cost and never consumes the key.
* Append-only JSONL audit log with a hash chain (user, tool, PII-masked arguments, result summary, trace id).
* Tenant scoping by user id carried in MCP `_meta` / `X-GigBid-User`, never as a model-chosen argument.

### Which agent may call what (`agent/mcp_client.py`, enforced by `ToolGateway`)

| Agent | Tools |
|---|---|
| scout | `search_jobs`, `get_job` |
| analyst (Job Analyst) | none |
| risk_assessor | `get_client_history`, `get_job` |
| fit_matcher, writer, critic | `search_evidence`, `get_case_study`, `list_skills` |
| pricing | `get_market_stats`, `get_connects_balance`, `get_job` |
| compliance | `get_platform_policy` |
| submitter (approval-gated executor) | `create_proposal_draft`, `submit_proposal` |
| client_liaison | marketplace reads + `send_message`, workspace tools, `search_evidence` |

## Third-party servers (not written by us)

| Server | Used for | Transport / auth | Trust rationale |
|---|---|---|---|
| **Upwork official MCP** (`https://mcp.upwork.com/mcp`) | live marketplace adapter (`marketplace.mode: upwork_live`) | Streamable HTTP, OAuth 2.1 authorization code + PKCE, per-user tokens encrypted with Fernet (`APP_SECRET_KEY`) | Operated by the platform whose data it is, so using it is the sanctioned alternative to scraping; we only create drafts through it and the user confirms on Upwork. |
| **GitHub MCP server** (`github/github-mcp-server`, remote `https://api.githubcopilot.com/mcp/` or the Docker image) | ingesting repo READMEs/code for RAG (agent `ingest`: `get_file_contents`, `search_repositories`, `search_code`, `list_commits`) | Streamable HTTP or stdio; fine-grained read-only PAT in `GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_READ_ONLY=1` for the Docker image | Maintained by GitHub, widely used, open source; run read-only with a least-privilege token scoped to the user's own repos. |

Both are optional entries in `agent.mcp_client.build_connections(..., include_optional=["upwork", "github"])`.

## What is tested, and what is not (honest status)

* Tested through in-memory MCP clients: every own tool (schemas, constraints, annotations, auth failure over ASGI, rate limit,
  idempotent retry incl. across a simulated restart, dry run, tenant isolation, audit log masking/chain).
* Tested against the real GigSim app over ASGI (`mcp_servers/marketplace/tests/test_gigsim_integration.py`).
* Tested over real Streamable HTTP with bearer auth and `MultiServerMCPClient` (`tests/integration/test_mcp_http.py`), including
  killing the marketplace server (UI-facing degraded status, queued write) and recovery.
* **NOT tested live: the Upwork adapter.** There are no Upwork credentials in this project. `upwork_live.py` and the OAuth
  helper are unit-tested only against a fake MCP session and a mocked token endpoint. The Upwork tool names in
  `DEFAULT_TOOL_MAP` are PLACEHOLDERS (the official tool list was not verifiable here): after connecting an account, run
  `python -m mcp_servers.marketplace.adapters.upwork_live --list-tools <user>` and override the mapping with env
  `UPWORK_TOOL_MAP`. Not mapped on the live side: `get_market_stats`, `get_proposal`, and `list_events` unless configured;
  `get_platform_policy` returns a static stub (no rules) so the local policy pack applies.
* The Workspace server is a local mock (JSON file, deterministic working-hours calendar), not Google Calendar/Gmail.
* MCP Inspector screenshots are not produced by this repo's tests; use
  `npx @modelcontextprotocol/inspector python -m mcp_servers.marketplace` (set `MARKETPLACE_STATE_DIR` and GigSim env first).

## R&D question A (tool granularity)

`python -m evals.runners.tool_design_eval` compares 35 fine-grained tools, 4 coarse tools and the deployed set with rewritten
descriptions (plus a terse-description ablation) on `evals/datasets/tool_tasks.jsonl` (40 tasks with known-correct calls) and writes
`evals/results/tool_design.json`, whose `meta.selector` says which selector produced the numbers. The default offline
baseline is a keyword/regex router and its numbers are **not** an LLM result; run `--selector llm` with a configured model for those.
