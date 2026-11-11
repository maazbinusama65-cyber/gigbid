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

(Add your own findings here before submitting: the viva expects you to know where the assistant was wrong.)
