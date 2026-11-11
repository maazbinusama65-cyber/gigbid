# Architecture

```
 Web (React/TS)  --SSE/REST-->  FastAPI  --(Arq jobs on Redis)-->  Worker
                                   |                                  |
                                   v                                  v
                          LangGraph runtime  (bid graph, conversation graph)
                          Postgres checkpointer + LangGraph store (memory)
                                   |  every capability = an MCP tool (allowlist per agent)
              +--------------------+----------------------+
              v                    v                      v
      Portfolio MCP (read)  Marketplace MCP (read+write)  Workspace MCP
      rag/ retriever          adapters: GigSim | Upwork-live   calendar + email drafts
      claim verification      idempotency, dry_run, audit,
                              bearer auth, rate limit
```

Rendered from code: [`images/bid_graph.mmd`](images/bid_graph.mmd),
[`images/conversation_graph.mmd`](images/conversation_graph.mmd) (`make graphs`).

## Bid graph (one thread per job)

`scout -> {analyst | risk_assessor | fit_matcher} (parallel, Send) -> decision -> pricing -> writer -> verifier
-> critic (<=2 send-backs) -> compliance -> dry_run -> approval (interrupt) -> submit`

| Agent | Why it exists (and could not be merged away) | Tools |
|---|---|---|
| Scout | De-duplicates and hands a job in; the only node that talks to the job feed | marketplace read |
| Job Analyst | Turns prose into a `JobSpec`; the contract everything else reads | none |
| Risk Assessor | Client quality + scam / free-work / off-platform / injection flags, independent of whether we *can* do the job | marketplace read |
| Fit Matcher | Requirement -> evidence matrix (the proof the Writer and the UI show) | portfolio read |
| Decision (rules) | skip / watch / bid from config thresholds; no LLM so it is testable and cheap | none |
| Pricing Strategist | Bid from market stats, client budget, the user's floor, Connects ROI | marketplace read |
| Proposal Writer | Cover letter + screening answers, every claim cites an evidence id | portfolio read |
| Verifier | Claim-level grounding; removes/rewrites unsupported claims *before* the Critic | none |
| Critic | Personalisation, opening, length, grounding; sends back at most twice | portfolio read |
| Compliance Guard | Policy pack as data; strips contact details/guarantees/injected payloads; can block with a reason | policy read |
| Approval + submit | `interrupt()` with draft, evidence, risk, price, dry-run; submit is idempotent and refuses without approval | marketplace write (draft/submit only) |

Fit Matcher cannot wait for the Analyst (they run in parallel), so requirement extraction is a shared
deterministic helper (`agent/nodes/analyst.py::extract_requirements`); the Analyst adds hidden needs and LLM
refinement afterwards.

## State / trace / memory (kept apart)

* **State** (`agent/state.py`): what this job needs now; typed, reducers on the keys parallel branches share
  (`evidence` union-by-id, `errors`, `steps`, `critiques`, `approvals`). Checkpointed.
* **Execution trace** (`agent/trace.py`): every node start/end, tool name, args, result digest, latency, tokens,
  PII-masked, JSONL per run, streamed to the UI. Not in graph state.
* **Long-term memory** (`agent/memory/`): a LangGraph store with two stores, *style* (learned from edits) and
  *outcome* (what got replies per job category). Observations are staged; only `promotion_rules.py` promotes them.

## Marketplace port

`agent/marketplace_port.py` is the only interface the graph sees. `McpMarketplacePort` calls the Marketplace MCP
server; the server selects `adapters/gigsim.py` or `adapters/upwork_live.py` from `marketplace.mode` in config.
Switching to live changes one config value and the credentials, nothing in `agent/`.

## Failure handling

Per-node timeout + bounded retry, `ToolUnavailable` -> thread goes to `needs_attention` (UI banner, work queued,
recovers), exhausted retries -> `dead_letter`, step and token budgets -> `needs_attention`. LLM calls retry with
backoff and fall back to a second model per node.

Decisions are recorded in [`adr/`](adr/).
