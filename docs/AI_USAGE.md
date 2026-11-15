# AI usage disclosure

I used **Claude Code** (Anthropic's coding agent, Sonnet 5.5, running in the Claude desktop app) as the main
implementation assistant, including parallel sub-agents for separate modules. I reviewed the architecture
decisions, ran the tests and accept responsibility for every line.

| Area | Files | How the assistant was used |
|---|---|---|
| Agent core | `agent/**` | Drafted the graphs, nodes, memory, LLM layer; I specified the topology, state/trace/memory split and promotion rules |
| MCP servers + gateway | `mcp_servers/**`, `agent/tools.py`, `agent/mcp_client.py` | Built against the contract in `docs/INTERFACES.md` |
| RAG | `rag/**`, `evals/runners/rag_eval.py` | Variants V0-V9, claim verifier, eval harness |
| GigSim stand-in + data | `gigsim/**`, `data/` generators | The instructor's GigSim was not in the starter kit I received, so a stand-in was generated |
| API + web | `apps/**` | FastAPI routers, React screens, Playwright specs |
| Docs | `docs/**`, `README.md` | Drafted; numbers are copied from `evals/results/` only |

## Things the assistant got wrong that were caught

1. **Interrupts swallowed by the retry wrapper.** The per-node retry wrapper caught `Exception`, which also
   catches LangGraph's `GraphInterrupt`, so the approval node was retried twice and then dead-lettered instead
   of pausing. Caught by `tests/unit/test_bid_graph.py::test_bid_pauses_for_approval_then_submits_exactly_once`;
   fixed by re-raising `GraphBubbleUp` in `agent/nodes/common.py`.
2. **Windows-illegal trace file names.** Run ids contain `:` (`bid:user:job`), which cannot be a Windows file
   name; the first run crashed with `Errno 22`. Fixed by sanitising the file name in `agent/trace.py`.
3. **A "benchmark" that sent graph definitions to a third party.** Rendering the graph PNG through
   `mermaid.ink` was blocked by the tool's safety classifier; PNG export is now opt-in and the Mermaid source is
   the committed artefact.

4. **Near-duplicate detection forgot after a restart.** The word-set index lived in memory and was only filled
   for first-seen jobs, so an original that hit the persisted exact-fingerprint row never got indexed and its
   near-duplicates slipped through. The failure taxonomy showed it (missed duplicates in
   `evals/results/failure_taxonomy_before_fixes.json`); fixed by persisting token sets, with a regression test.
5. **Injected screening questions reached the job spec.** The sanitiser stripped the description but copied the
   screening questions verbatim, and scam rules read the unstripped text so injected "guarantee 100%" text made
   legitimate jobs look like scams. Fixed in `agent/guardrails.py`, `agent/nodes/risk.py`, with tests.
6. **A loose attack-success metric.** The first injection metric also counted any fit of 0.99 or higher on a
   skip-gold job, which a genuine perfect match triggers. It was tightened to canary leakage or a $1 quote, and the
   fit-based count is reported separately. The two figures are therefore not directly comparable.
7. **A crash scored as a correct skip.** A requirement of one character ("R") was rejected by the search tool on
   every retry; the Decision node then ran on missing data and overwrote the dead-letter with "skip", so the
   metrics counted the crash as a (sometimes correct) skip. Found by reading one trace. Fixed by widening the
   query, by Decision refusing to run after a failed branch, and by a CI check on dead-lettered jobs.
8. **The evaluation harness hid jobs.** GigSim hides jobs posted after its simulated clock, so one late-posted dev
   job raised not-found. The harness now advances the clock before reading.
9. **Outcome rates read from the wrong field.** The first outcomes run reported 0 replies of 110 because I read
   the final proposal status; an unanswered reply is auto-marked "lost" after 72 simulated hours. Outcomes are now
   read from the event log.
10. **Retrieval latency measured under load.** The latencies stored with the RAG variants were taken while other
    jobs used the CPU and were order-dependent (the naive baseline read slower than the skill graph). They were
    re-measured on an idle machine (`evals/results/rag_latency.json`) and the old figures are no longer quoted.
11. **A better pipeline found but not shipped.** The ablation showed that decomposition plus hybrid plus skill graph
    beats the skill graph alone. By then the decision, outcome and X2 results had all been measured on the shipped
    variant, so it was left as is and the gap is stated in the report.
12. **The configured retrieval variant was never used.** The Portfolio server read only the `RAG_VARIANT` environment
    variable and fell back to a hard-coded `v3_rerank`, ignoring `rag.variant` in the config, so every system-level run
    (decisions, outcomes, A/B) used V3 while the documents said V9. Found while preparing deployment. The server now reads
    the config (with a regression test); the affected results are labelled as V3 until they are re-run.
13. **A fresh install would have broken.** An unpinned `mcp` dependency resolves to the 2.x line, which renamed the
    API this code uses; pinned to `mcp<2`. Old Dockerfiles also copied a file that does not exist and lacked the data
    directories; the new deployment files do not.

(Add your own findings here before submitting: the viva expects you to know where the assistant was wrong.)
