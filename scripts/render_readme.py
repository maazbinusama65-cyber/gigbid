"""Render README.md from the results in evals/results/ so every number is traceable.

    python scripts/render_readme.py

Each number is written with a trailing marker `<!--r:<file>:<key>-->` that scripts/ci_rules.py checks. Results that
do not exist yet render as "not run" instead of a number.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "evals" / "results"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")


def load(name: str) -> dict | None:
    p = RES / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def cite(file: str, key: str, text: str) -> str:
    return f"{text}<!--r:{file}:{key}-->"


def pct(x: float | None, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def clean_latency(variant: str) -> dict | None:
    d = load("rag_latency.json")
    return (d or {}).get("variants", {}).get(variant)


def retrieval_table() -> str:
    d = load("rag_variants.json")
    if not d:
        return "_not run_"
    rows = ["| Variant | Recall@5 | MRR | nDCG@10 | p50 ms per job | p95 ms per job |", "|---|---|---|---|---|---|"]
    for name, v in d["variants"].items():
        o = v["overall"]
        lat = clean_latency(name)
        p50 = f"{lat['p50_ms']:.0f}" if lat else "-"
        p95 = f"{lat['p95_ms']:.0f}" if lat else "-"
        recall = cite("rag_variants.json", "recall5", f"{100 * o['recall5']:.1f}")
        rows.append(f"| `{name}` | {recall} | {o['mrr']:.3f} | {o['ndcg10']:.3f} | {p50} | {p95} |")
    return "\n".join(rows) + ("\n\nLatency is per job (all requirements), cold query caches, measured on an idle machine for the variants "
                              "shown (`-` = not re-measured; see `rag_latency.json`)." if load("rag_latency.json") else "")


def decision_table(fname: str) -> str:
    d = load(fname)
    if not d:
        return "_not run_"
    rows = ["| Persona | Jobs | Bid-or-skip F1 | Scam precision / recall | Price in fair band | Injection attack success | "
            "Unsupported claims / proposal (after verification) | p50 / p95 latency (s) |",
            "|---|---|---|---|---|---|---|---|"]
    for p in PERSONAS:
        r = d["per_persona"][p]
        rows.append(
            f"| {p} | {r['n_jobs']} | {cite(fname, 'f1', f'{r['bid_or_skip']['f1']:.3f}')} | "
            f"{r['scam_detection']['precision']:.2f} / {r['scam_detection']['recall']:.2f} | "
            f"{pct(r['price_in_fair_band']['rate'])} (n={r['price_in_fair_band']['n']}) | "
            f"{cite(fname, 'attack_success', str(r['injection']['attack_success']))} / {r['injection']['n']} | "
            f"{r['unsupported_claims_per_proposal']['after_verification']} | "
            f"{r['latency_s']['p50']:.1f} / {r['latency_s']['p95']:.1f} |")
    return "\n".join(rows)


def taxonomy_table() -> str:
    d = load("failure_taxonomy.json")
    if not d:
        return "_not run_"
    rows = ["| Category | Count | What it means |", "|---|---|---|"]
    for name, c in d["categories"].items():
        rows.append(f"| `{name}` | {cite('failure_taxonomy.json', 'count', str(c['count']))} | {c['description']} |")
    return "\n".join(rows) + f"\n\nTotal wrong bid-or-skip decisions on the dev set: {d['total_failures']}."


def verify_block() -> str:
    d = load("rag_verify.json")
    if not d:
        return "_not run_"
    c, f, t = d["claim_level"], d["fabrication_detection"], d["true_claims"]
    return (f"On {d['protocol']['drafts']} drafts with deliberately fabricated claims, the verifier detected "
            f"{cite('rag_verify.json', 'recall', pct(min(x['recall'] for x in f.values()), 0))} of fabricated clients, years, "
            f"metrics and tools. It flagged {pct(t['false_flag_rate'])} of true claims by mistake. Over "
            f"{c['n_claims_before']} claims, unsupported claims went from {c['unsupported_before']} before repair to "
            f"{cite('rag_verify.json', 'unsupported_after', str(c['unsupported_after']))} after.")


def tool_table() -> str:
    d = load("tool_design.json")
    if not d:
        return "_not run_"
    rows = ["| Tool surface | Tools | Schema tokens | Tool-selection accuracy | Argument accuracy |", "|---|---|---|---|---|"]
    for k, v in d["sets"].items():
        rows.append(f"| {k}: {v['description']} | {v['n_tools']} | {v['schema_tokens']} | "
                    f"{cite('tool_design.json', 'tool_selection_accuracy', pct(v['tool_selection_accuracy']))} | "
                    f"{pct(v['argument_accuracy'])} |")
    return "\n".join(rows)


def outcomes_block() -> str:
    d = load("gigsim_outcomes_stub.json")
    if not d:
        return "_not run_"
    rows = ["| Persona | Proposals submitted | Replied | Reply rate (95% CI) | Connects per reply |", "|---|---|---|---|---|"]
    for p in PERSONAS:
        r = d["per_persona"][p]
        lo, hi = r["reply_rate_ci95"]
        rows.append(f"| {p} | {r['proposals_submitted']} | {r['replied']} | "
                    f"{cite('gigsim_outcomes_stub.json', 'reply_rate', pct(r['reply_rate']))} ({pct(lo)} to {pct(hi)}) | "
                    f"{r['connects_per_reply']} |")
    return "\n".join(rows)


def x2_block() -> str:
    d = load("x2_experiment.json")
    if not d:
        return "_not run_"
    a, b = d["strategies"]
    pooled = d["pooled"]
    z = pooled["unpaired_z_test"]
    return (f"Strategy A `{a}`: {cite('x2_experiment.json', 'rate', pct(pooled[a]['rate']))} replies "
            f"({pooled[a]['replied']}/{pooled[a]['n']}). Strategy B `{b}`: {pct(pooled[b]['rate'])} "
            f"({pooled[b]['replied']}/{pooled[b]['n']}). Unpaired z-test p = {z['p']}; paired exact McNemar p = "
            f"{cite('x2_experiment.json', 'mcnemar_exact_p', str(pooled['mcnemar_exact_p']))}.")


def ablation_block() -> str:
    d = load("rag_ablation.json")
    if not d:
        return "_not run_"
    bp = d["best_pipeline"]
    rows = ["| Component removed | Recall@5 | Delta Recall@5 (95% CI) |", "|---|---|---|"]
    for x in d["ablations"]:
        lo, hi = x["recall5_delta_ci95"]
        d_pts = cite("rag_ablation.json", "recall5_delta_points", f"{x['recall5_delta_points']:+.1f}")
        rows.append(f"| {x['removed']} | {100 * x['recall5']:.1f} | {d_pts} ({lo:+.1f} to {hi:+.1f}) |")
    biggest = min(d["ablations"], key=lambda x: x["recall5_delta_points"])
    decomp = next((x for x in d["ablations"] if "decomposition" in x["removed"]), None)
    note = ""
    if decomp:
        falsified = biggest is not decomp
        note = ("\n\n" + f"Pre-registered ablation hypothesis (removing decomposition costs the most): **{'FALSIFIED' if falsified else 'supported'}**. "
                f"The biggest drop is removing {biggest['removed']} ({biggest['recall5_delta_points']:+.1f} points); removing decomposition "
                f"changes Recall@5 by {decomp['recall5_delta_points']:+.1f}.")
    head = (f"Best lightweight pipeline `{bp['name']}`: Recall@5 {100 * bp['recall5']:.1f} "
            "(selected on the same dev jobs, so optimistic; the deltas are the point).\n\n")
    return head + "\n".join(rows) + note


def reply_vs_retrieval_block() -> str:
    base, best = load("gigsim_outcomes_stub_v0_naive.json"), load("gigsim_outcomes_stub.json")
    if not (base and best):
        return "_not run_"
    rows = ["| Retrieval | Proposals | Reply rate (95% CI) |", "|---|---|---|"]
    for label, f, d in (("v0_naive", "gigsim_outcomes_stub_v0_naive.json", base), ("v9_skill_graph (shipped)", "gigsim_outcomes_stub.json", best)):
        o = d["overall"]
        lo, hi = o["reply_rate_ci95"]
        rows.append(f"| {label} | {o['proposals_submitted']} | {cite(f, 'reply_rate', pct(o['reply_rate']))} ({pct(lo)} to {pct(hi)}) |")
    return "\n".join(rows)


def judge_block() -> str:
    d = load("judge_calibration_report.json")
    if not d or d.get("status") != "ok":
        return "_awaiting human labels or judge scores_"
    kb = cite("judge_calibration_report.json", "kappa_binary_good_ge4", f"{d['kappa_binary_good_ge4']:.2f}")
    return (f"Judge `openai/gpt-oss-120b` against my own 30 labels (rubric 1 to 5; good means 4 or above): binary "
            f"Cohen's kappa {kb}, quadratic-weighted ordinal kappa {d['kappa_ordinal_quadratic']:.2f}, unweighted "
            f"ordinal kappa {d['kappa_ordinal_unweighted']:.2f}, exact agreement {pct(d['exact_agreement'], 0)} "
            f"(n={d['n']}). The judge is more lenient than I am (mean score {d['mean_judge']:.2f} against "
            f"{d['mean_human']:.2f}), so it is usable for ranking proposals but should not be read as an absolute "
            f"quality score.")


def h1_block() -> str:
    d = load("rag_variants.json")
    if not d:
        return "_not run_"
    h = d["hypothesis_test"]
    lo, hi = h["ci95_points"]
    return (f"{d['hypothesis']['statement']} Measured gain: "
            f"{cite('rag_variants.json', 'gain_points', f'{h['gain_points']:.2f}')} points (95% CI {lo:.1f} to {hi:.1f}, "
            f"n={h['n_jobs']} jobs). Verdict: **{h['verdict']}**.")


def graph(name: str) -> str:
    p = ROOT / "docs" / "images" / name
    return f"```mermaid\n{p.read_text(encoding='utf-8').strip()}\n```" if p.exists() else ""


TEMPLATE = """# GigBid: a multi-agent freelancer copilot

GigBid watches a freelancer marketplace, decides which jobs are worth a bid, drafts a proposal in which every claim
is backed by the freelancer's own portfolio, and **stops for human approval before anything is sent**. It is the
AI-4016 R&D assignment built end to end: LangGraph agents, three MCP servers, an advanced RAG stack with claim
verification, a FastAPI + React app, a Redis worker, and an evaluation harness that gates CI.

> **Read this first: what is and is not proven here.**
> * The instructor's `gigsim/`, personas and test set were **not** in the starter kit I received. `gigsim/` is my own
>   stand-in simulator and every job, client and gold label is synthetic (some history titles and budgets come from a
>   real Kaggle Upwork dump; see `docs/DATA_CARD.md`). Numbers below are on that stand-in data.
> * All agent numbers use the deterministic **`stub` model profile** (no LLM calls). They test routing, retrieval,
>   policy, safety and plumbing. They say little about the *writing quality* an LLM would produce.
> * Dev numbers were used while tuning, so they are optimistic; the held-out test split was never tuned on.
> * Not done: public deployment, the demo video, judge-calibration kappa (needs 30 human labels), live Upwork.
>   Details are under **Known gaps**.

## Architecture

Bid graph (Scout, then Analyst / Risk / Fit Matcher in parallel through `Send`, Decision, Pricing, Writer, Verifier,
Critic loop with at most two send-backs, Compliance Guard, human approval through `interrupt()`, submit):

{bid_graph}

Conversation graph:

{conv_graph}

Design notes live in `docs/ARCHITECTURE.md` and `docs/adr/`. Short version: state, trace and long-term memory are
separate; policy is data (`agent/policy_rules.yaml` plus the marketplace's own policy endpoint); a submit is
exactly-once through a deterministic thread id plus the marketplace idempotency key; job text is untrusted and is
delimited and stripped before any model sees it.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\\Scripts\\activate
make install
make seed          # deterministic personas, jobs and gold labels
make gigsim        # marketplace simulator on :8081 (terminal 1)
make api           # FastAPI on :8000, real services (terminal 2)
make web           # React app on :5173 (terminal 3)
make test          # unit + contract + integration, offline
```

Or `docker compose -f infra/docker-compose.yml up` (compose file validated, images not built in my environment).
Copy `.env.example` to `.env` for local values; nothing secret is committed. The LLM key is only read at runtime.

## Results (stub model profile)

### Bid-or-skip decisions, held-out test split (100 jobs per persona, never tuned on)

{test_table}

### Same, dev split (200 jobs per persona, used while tuning)

{dev_table}

The scam and injection patterns were tuned on the dev jobs, so the dev rows flatter the agent. The held-out table is
the one to trust. Its weakest cell is scam recall on `data_analyst`, which I did **not** tune.

### Retrieval variants (evidence Recall@5 over portfolio items)

{retrieval}

Shipped variant: `v9_skill_graph`, the best single variant. The ablation found a better lightweight pipeline (see below) that I did not ship because the decision, outcome and X2 results were all measured on V9. **Pre-registered hypothesis H1:** {h1}

### Where better retrieval did or did not change the reply rate

{reply_vs_retrieval}

### Ablation

{ablation}

### Claim verification

{verify}

### LLM-judge calibration

{judge}

### Tool granularity (R&D question A)

{tools}

**Caveat:** these accuracies come from an offline keyword-and-regex selector, **not an LLM**. They measure how
separable the tool sets are lexically and must not be read as model behaviour. The LLM version is not run yet.

### Outcomes in the simulator (reply rate of approved proposals)

{outcomes}

Interview and hire need the freelancer to answer within 72 simulated hours; the batch run never answers, so only reply
rate is reported. GigSim clients are rule-based, so this shows the pipeline can measure an effect, not that the effect
exists on a real marketplace.

### Signature extension X2: proposal A/B experiment

{x2}

See `docs/EXTENSION.md` for the design and its limits.

### Failure taxonomy (dev set)

{taxonomy}

## Safety

Job posts, screening questions and client messages are untrusted. They are delimited, injected sentences are
stripped, scam signals are read from the stripped text, injected screening questions are dropped, outgoing text passes
a Compliance Guard, and nothing is sent without an approval that names the exact draft. A real bug found on the way
(near-duplicate postings slipping through after a restart) and the other mistakes made are in `docs/AI_USAGE.md`.

## Known gaps

* No public deployment or reviewer login yet; the app runs locally and under `docker compose`.
* No demo video; screenshots are in `docs/screenshots/`.
* Real-LLM runs (writer quality, model comparison, R&D question C single agent vs supervisor vs graph) are not done.
* Live Upwork OAuth is not connected; the marketplace port has a GigSim adapter and a live-Upwork adapter whose tool
  names are placeholders until a real server is attached.
* The 30 s per-job latency budget is exceeded at p95 on one persona (see the tables).

## Repository map

`agent/` graphs, nodes, prompts, policy, memory, runtime. `mcp_servers/` Portfolio, Marketplace and Workspace servers.
`rag/` retrieval variants and claim verification. `apps/api` FastAPI, `apps/web` React. `worker/` Redis worker.
`gigsim/` simulator (stand-in, hash-checked in CI). `evals/` harness, runners and results. `docs/` architecture,
ADRs, tool design, runbook, data card, AI usage. `infra/` compose and Dockerfiles. `scripts/ci_rules.py` enforces:
no secrets, `gigsim/` unchanged, prompts only in `agent/prompts/`, every README number traceable to `evals/results/`.

Regenerate this file with `python scripts/render_readme.py`.
"""


def main() -> None:
    out = TEMPLATE.format(
        bid_graph=graph("bid_graph.mmd"), conv_graph=graph("conversation_graph.mmd"),
        test_table=decision_table("decision_stub_test.json"), dev_table=decision_table("decision_stub.json"),
        retrieval=retrieval_table(), h1=h1_block(), verify=verify_block(), tools=tool_table(),
        judge=judge_block(), ablation=ablation_block(), reply_vs_retrieval=reply_vs_retrieval_block(), outcomes=outcomes_block(), x2=x2_block(), taxonomy=taxonomy_table())
    (ROOT / "README.md").write_text(out, encoding="utf-8")
    print("README.md written", len(out), "chars")


if __name__ == "__main__":
    main()
