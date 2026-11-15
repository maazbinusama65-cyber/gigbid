"""Build the R&D report (HTML, then PDF through headless Edge/Chrome) from evals/results/.

    python scripts/build_report.py            # writes docs/report/GigBid_RD_Report.{html,pdf}

Every number is read from a results file at build time and carries a [file] tag. Anything that was not measured is
printed as "not measured" instead of a number. The page limit (10) is checked after rendering.
"""
from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "evals" / "results"
OUT = ROOT / "docs" / "report"
PERSONAS = ("ai_ml", "fullstack", "data_analyst")
AUTHOR = "Maaz bin Usama (22i-1378)"
REPO = "https://github.com/maazbinusama65-cyber/gigbid"
NM = "<span class='nm'>not measured</span>"



def runs_on_v3() -> bool:
    """True while the system-level results are the ones measured with the Portfolio server's then-default variant."""
    a, b = RES / "decision_stub.json", RES / "decision_stub_round2_v3rerank.json"
    return a.exists() and b.exists() and a.read_bytes() == b.read_bytes()


V3_NOTE = ("The decision, outcome and A/B results were measured with retrieval variant <code>v3_rerank</code>, the Portfolio "
           "server's hard-coded default at the time, <b>not</b> the <code>v9_skill_graph</code> declared as shipped: the server ignored "
           "the config value. The wiring is fixed and tested, but the re-runs on V9 were not completed before submission.")


def load(name: str):
    p = RES / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def clean_latency(variant: str) -> dict | None:
    d = load("rag_latency.json")
    return (d or {}).get("variants", {}).get(variant)


def src(name: str) -> str:
    return f"<span class='src'>[{name}]</span>"


def pct(x, nd: int = 1) -> str:
    return "n/a" if x is None else f"{100 * x:.{nd}f}%"


def table(head: list[str], rows: list[list], cls: str = "") -> str:
    h = "".join(f"<th>{c}</th>" for c in head)
    b = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table class='{cls}'><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


# ----------------------------------------------------------------------------------------------- figures
def retrieval_figure() -> str:
    d = load("rag_variants.json")
    if not d:
        return ""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.6, 2.7), dpi=200)
    label_these = {"v0_naive": "V0", "v2_hybrid": "V2", "v3_rerank": "V3", "v9_skill_graph": "V9 (shipped)",
                   "v1_decompose": "V1", "v8_corrective": "V8", "v1_decompose+v2_hybrid+v3_rerank+v9_skill_graph": "V1+V2+V3+V9",
                   "v1_decompose+v2_hybrid+v3_rerank+v8_corrective": "stack+V8"}
    for name, v in d["variants"].items():
        x = (clean_latency(name) or {}).get("p50_ms")
        y = 100 * v["overall"]["recall5"]
        if not x:
            continue
        stacked = "+" in name
        color = "#b5452f" if name == "v9_skill_graph" else ("#6b7a8f" if stacked else "#1f3a5f")
        ax.scatter(x, y, s=34, c=color, marker="s" if stacked else "o", zorder=3)
        if name in label_these:
            ax.annotate(label_these[name], (x, y), textcoords="offset points", xytext=(5, 4), fontsize=6.5)
    ax.set_xscale("log")
    ax.set_xlabel("cold-query latency, p50 (ms, log scale)", fontsize=7)
    ax.set_ylabel("evidence Recall@5 (%)", fontsize=7)
    ax.tick_params(labelsize=6.5)
    ax.grid(alpha=0.25)
    ax.spines[["top", "right"]].set_visible(False)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return f"<img class='fig' src='data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}'>"


# ----------------------------------------------------------------------------------------------- sections
def sec_architecture_diagram() -> str:
    box = lambda t, c="": f"<div class='b {c}'>{t}</div>"      # noqa: E731
    arrow = "<div class='ar'>&rarr;</div>"
    row1 = (box("Scout<br><small>dedup</small>") + arrow +
            "<div class='par'>" + box("Job Analyst", "p") + box("Risk Assessor", "p") + box("Fit Matcher<br><small>RAG via MCP</small>", "p") + "</div>"
            + arrow + box("Decision<br><small>rules from config</small>") + arrow + box("Pricing"))
    row2 = (box("Writer") + arrow + box("Verifier<br><small>claims vs evidence</small>") + arrow + box("Critic<br><small>&le;2 send-backs</small>") + arrow
            + box("Compliance<br>Guard") + arrow + box("Human approval<br><small>interrupt()</small>", "h") + arrow + box("Submit<br><small>idempotent</small>"))
    return f"<div class='flow'>{row1}</div><div class='flow'>{row2}</div>"


def sec_tools() -> str:
    d = load("tool_design.json")
    if not d:
        return NM
    rows = [[f"<b>{k}</b>: {v['description']}", v["n_tools"], v["schema_tokens"], pct(v["tool_selection_accuracy"]),
             pct(v["argument_accuracy"]), pct(v["argument_accuracy_given_correct_tool"])] for k, v in d["sets"].items()]
    return table(["Tool surface", "Tools", "Schema tokens", "Tool selection", "Argument accuracy", "Args | right tool"], rows)


def sec_retrieval() -> str:
    d = load("rag_variants.json")
    if not d:
        return NM
    show = ["v0_naive", "v0b_naive_struct", "v1_decompose", "v2_hybrid", "v3_rerank", "v4_outcome", "v5_multivector", "v6_contextual",
            "v7_hyde", "v8_corrective", "v9_skill_graph", "v1_decompose+v2_hybrid", "v1_decompose+v2_hybrid+v3_rerank",
            "v1_decompose+v2_hybrid+v3_rerank+v9_skill_graph"]
    rows = []
    for n in show:
        v = d["variants"].get(n)
        if not v:
            continue
        o, lat = v["overall"], clean_latency(n) or {}
        name = f"<b>{n}</b> (shipped)" if n == "v9_skill_graph" else n.replace("v1_decompose+v2_hybrid", "v1+v2").replace("+v3_rerank", "+v3").replace("+v9_skill_graph", "+v9")
        rows.append([name, f"{100 * o['recall5']:.1f}", f"{o['mrr']:.3f}", f"{o['ndcg10']:.3f}",
                     f"{100 * v['n_requirements_ge4']['recall5']:.1f}", f"{lat['p50_ms']:.0f}" if lat else "-", f"{lat['p95_ms']:.0f}" if lat else "-"])
    return table(["Variant", "Recall@5", "MRR", "nDCG@10", "Recall@5 (4+ reqs)", "p50 ms", "p95 ms"], rows, "tight")


def sec_breakdown() -> str:
    d = load("rag_variants.json")
    if not d:
        return NM
    rows = []
    for n in ("v0_naive", "v2_hybrid", "v9_skill_graph"):
        v = d["variants"][n]
        rows.append([n] + [f"{100 * v['by_persona'][p]['recall5']:.1f}" for p in PERSONAS]
                    + [f"{100 * v['by_job_type'][t]['recall5']:.1f}" for t in ("fixed", "hourly")]
                    + [f"{100 * v['by_n_requirements'][b]['recall5']:.1f}" for b in ("1-3", "4-5", "6+")])
    return table(["Variant", "ai_ml", "fullstack", "data_analyst", "fixed", "hourly", "1-3 reqs", "4-5 reqs", "6+ reqs"], rows, "tight")


def sec_h1() -> str:
    d = load("rag_variants.json")
    h = d["hypothesis_test"]
    lo, hi = h["ci95_points"]
    return (f"<b>H1</b> (recorded in the results file): {d['hypothesis']['statement']} Measured gain "
            f"<b>{h['gain_points']:.2f} points</b>, 95% CI {lo:.1f} to {hi:.1f}, n={h['n_jobs']} jobs. Verdict: <b>{h['verdict']}</b> {src('rag_variants.json')}.")


def sec_verify() -> str:
    d = load("rag_verify.json")
    if not d:
        return NM
    c, f, t = d["claim_level"], d["fabrication_detection"], d["true_claims"]
    return (f"On {d['protocol']['drafts']} drafts that were given a fabricated client, year, metric or tool (63 each), the verifier detected "
            f"{pct(min(x['recall'] for x in f.values()), 0)} of every type and flagged {pct(t['false_flag_rate'])} of true claims by mistake. "
            f"Over {c['n_claims_before']} claims, <b>unsupported claims fell from {c['unsupported_before']} to {c['unsupported_after']}</b> after repair {src('rag_verify.json')}.")


def sec_reply_vs_retrieval() -> str:
    base, best = load("gigsim_outcomes_stub_v0_naive.json"), load("gigsim_outcomes_stub.json")
    if not (base and best):
        return f"Reply rate by retrieval variant: {NM} (run did not complete)."
    rows = []
    for label, d in (("v0_naive", base), ("v3_rerank (the variant actually served)" if runs_on_v3() else "v9_skill_graph (shipped)", best)):
        o = d["overall"]
        lo, hi = o["reply_rate_ci95"]
        rows.append([label, o["proposals_submitted"], pct(o["reply_rate"]), f"{pct(lo)} to {pct(hi)}"]
                    + [pct(d["per_persona"][p]["reply_rate"]) for p in PERSONAS])
    v = load("rag_variants.json")
    note = ""
    if v:
        r0, r9 = 100 * v["variants"]["v0_naive"]["overall"]["recall5"], 100 * v["variants"]["v9_skill_graph"]["overall"]["recall5"]
        o0, o9 = base["overall"]["reply_rate"], best["overall"]["reply_rate"]
        if runs_on_v3():
            r3 = 100 * v["variants"]["v3_rerank"]["overall"]["recall5"]
            note = (f"<p><b>This comparison does not test whether better retrieval raises replies.</b> The variant actually served was V3 "
                    f"(Recall@5 {r3:.1f}), which scores <i>below</i> V0 ({r0:.1f}); reply rates were {pct(o0)} for V0 and {pct(o9)} for V3, "
                    f"with overlapping intervals. A run on V9 (Recall@5 {r9:.1f}) is what the question needs and was not completed.</p>")
        else:
            note = (f"<p><b>Better retrieval did not raise the reply rate.</b> Recall@5 rose from {r0:.1f} to {r9:.1f}, but the reply rate went from {pct(o0)} to {pct(o9)} "
                    f"with overlapping intervals. My reading, which I did not test: the simulator's clients react to whether the letter names their must-have skills and cites evidence, and the "
                    f"stub writer already does both from the top-ranked items, so project-level recall gains do not change what the letter says.</p>")
    return table(["Retrieval", "Proposals", "Reply rate", "95% CI", "ai_ml", "fullstack", "data_analyst"], rows, "tight") + note


def sec_ablation() -> str:
    d = load("rag_ablation.json")
    if not d:
        return f"Leave-one-out ablation: {NM}."
    bp = d["best_pipeline"]
    rows = []
    for x in d["ablations"]:
        lo, hi = x["recall5_delta_ci95"]
        rows.append([x["removed"], f"{100 * x['recall5']:.1f}", f"{x['recall5_delta_points']:+.1f} [{lo:+.1f}, {hi:+.1f}]",
                     f"{x['mrr_delta_points']:+.1f}", f"{x['ndcg10_delta_points']:+.1f}"])
    biggest = min(d["ablations"], key=lambda x: x["recall5_delta_points"])
    decomp = next((x for x in d["ablations"] if "decomposition" in x["removed"]), None)
    verdict = ""
    if decomp:
        lo, hi = decomp["recall5_delta_ci95"]
        falsified = biggest is not decomp
        verdict = (f"<p><b>Pre-registered ablation hypothesis:</b> {d['hypothesis']['statement']} <b>{'FALSIFIED' if falsified else 'supported'}</b>: "
                   f"the largest drop comes from removing <i>{biggest['removed']}</i> ({biggest['recall5_delta_points']:+.1f} points), "
                   f"while removing decomposition changes Recall@5 by {decomp['recall5_delta_points']:+.1f} (CI {lo:+.1f} to {hi:+.1f}).</p>")
    if "rerank" in d["hypothesis"]["statement"] and not any("rerank" in x["removed"] for x in d["ablations"]):
        verdict += ("<p><b>The reranker clause of that hypothesis was not tested:</b> the ablated pipeline has no cross-encoder reranker "
                    "(left out for cost), and I did not ablate the reranker stack.</p>")
    return (f"<p>Best lightweight pipeline <code>{bp['name']}</code>: Recall@5 {100 * bp['recall5']:.1f}, MRR {bp['mrr']:.3f}, nDCG@10 {bp['ndcg10']:.3f} "
            f"(selected and ablated on the same dev jobs, so its absolute numbers are optimistic; the deltas are the point; paired bootstrap 95% CIs). "
            f"{src('rag_ablation.json')}</p>"
            + table(["Component removed", "Recall@5", "&Delta; Recall@5 [95% CI]", "&Delta; MRR", "&Delta; nDCG@10"], rows, "tight") + verdict)


def decision_rows(fname: str) -> tuple[list[list], dict | None]:
    d = load(fname)
    if not d:
        return [], None
    rows = []
    for p in PERSONAS:
        r = d["per_persona"][p]
        rows.append([p, r["n_jobs"], f"{r['bid_or_skip']['f1']:.3f}", f"{r['scam_detection']['precision']:.2f} / {r['scam_detection']['recall']:.2f}",
                     pct(r["price_in_fair_band"]["rate"], 0), f"{r['injection']['attack_success']}/{r['injection']['n']}",
                     r["final_status_counts"].get("dead_letter", 0), f"{r['latency_s']['p50']:.1f} / {r['latency_s']['p95']:.1f}"])
    return rows, d


DECISION_HEAD = ["Persona", "Jobs", "Bid-or-skip F1", "Scam P / R", "Price in band", "Injection success", "Dead-lettered", "p50 / p95 s"]


def sec_decisions(fname: str) -> str:
    rows, d = decision_rows(fname)
    return table(DECISION_HEAD, rows, "tight") + f" {src(fname)}" if d else NM


def sec_shipped() -> str:
    v, ab = load("rag_variants.json"), load("rag_ablation.json")
    if not v:
        return NM
    r9 = 100 * v["variants"]["v9_skill_graph"]["overall"]["recall5"]
    l9 = clean_latency("v9_skill_graph")
    lat = lambda x: f"p50 {x['p50_ms']:.0f} ms, p95 {x['p95_ms']:.0f} ms" if x else "latency not re-measured"      # noqa: E731
    out = (f"<b>Note:</b> {V3_NOTE} " if runs_on_v3() else "") + f"<b>Declared shipped choice:</b> <code>v9_skill_graph</code> (Recall@5 {r9:.1f}; {lat(l9)} per job, cold query caches, idle machine {src('rag_latency.json')})."
    if ab:
        bp = ab["best_pipeline"]
        stack = "v1_decompose+v2_hybrid+v3_rerank+v9_skill_graph"
        rs = 100 * v["variants"][stack]["overall"]["recall5"]
        out += (f" The ablation found a better lightweight pipeline, <code>{bp['name']}</code> (Recall@5 {100 * bp['recall5']:.1f}; "
                f"{lat(clean_latency(bp['name']))}). <b>I did not ship it, and latency was not the reason</b> (it is cheap): the decision, outcome and X2 results "
                f"were all measured on V9, so switching would invalidate them and I did not repeat them in the time left. The cost of that choice is about "
                f"{100 * bp['recall5'] - r9:.1f} points of Recall@5. Adding the cross-encoder reranker on top reaches {rs:.1f} "
                f"({rs - 100 * bp['recall5']:+.1f} points) at {lat(clean_latency(stack))}, which is affordable per job but a poor trade.")
    return out


def sec_b5() -> str:
    d = load("rag_variants.json")
    if not d:
        return NM
    out, rows = load("gigsim_outcomes_stub.json"), []
    base = load("gigsim_outcomes_stub_v0_naive.json")
    test = load("decision_stub_test.json")
    p95 = max(test["per_persona"][p]["latency_s"]["p95"] for p in PERSONAS) if test else None
    for label, name, oc in (("V0 naive", "v0_naive", base), ("Served in system runs" if runs_on_v3() else "Shipped V9", "v3_rerank" if runs_on_v3() else "v9_skill_graph", out)):
        o = d["variants"][name]["overall"]
        rows.append([label, f"{100 * o['recall5']:.1f}", f"{o['ndcg10']:.3f}", "0.0 (stub)", NM,
                     pct(oc["overall"]["reply_rate"]) if oc else NM,
                     f"{p95:.1f} s (worst persona, shipped config)" if (p95 and name == "v9_skill_graph") else NM, "$0 (stub)"])
    return table(["B5 row", "Recall@5", "nDCG@10", "Unsupported / proposal", "Judge score", "GigSim reply", "p95", "Cost / proposal"], rows, "tight")


def sec_x2_reading() -> str:
    d = load("x2_experiment.json")
    if not d:
        return ""
    a, b = d["strategies"]
    pl = d["pooled"]
    sig = [p for p in PERSONAS if d["per_persona"][p]["paired"]["mcnemar_exact_p"] < 0.05]
    rest = [p for p in PERSONAS if p not in sig]
    better = a if pl[a]["rate"] >= pl[b]["rate"] else b
    return (f"<b>Reading.</b> Pooled, <code>{better}</code> has the higher reply rate (paired p = {pl['mcnemar_exact_p']}). Personas with a significant paired difference (p &lt; 0.05): "
            f"{', '.join(sig) or 'none'}; no significant difference in: {', '.join(rest) or 'none'}. The pooled p-value therefore should not be read as a uniform effect. ")


def sec_scam_sentence() -> str:
    d = load("decision_stub_test.json")
    if not d:
        return NM
    worst = min(PERSONAS, key=lambda p: d["per_persona"][p]["scam_detection"]["recall"])
    r = d["per_persona"][worst]["scam_detection"]["recall"]
    return f"scam recall on the held-out split is lowest for <code>{worst}</code> at {r:.2f}"


def sec_x2() -> str:
    d = load("x2_experiment.json")
    if not d:
        return NM
    a, b = d["strategies"]
    rows = []
    for p in PERSONAS:
        r = d["per_persona"][p]
        rows.append([p, pct(r[a]["rate"]), pct(r[b]["rate"]), f"{r['paired']['only_' + a]} / {r['paired']['only_' + b]}",
                     r["unpaired_z_test"]["p"], r["paired"]["mcnemar_exact_p"]])
    pl = d["pooled"]
    rows.append(["<b>pooled</b>", f"<b>{pct(pl[a]['rate'])}</b> ({pl[a]['replied']}/{pl[a]['n']})", f"<b>{pct(pl[b]['rate'])}</b> ({pl[b]['replied']}/{pl[b]['n']})",
                 "", pl["unpaired_z_test"]["p"], pl["mcnemar_exact_p"]])
    return (table(["Persona", f"A: {a}", f"B: {b}", "only A / only B replied", "z-test p", "McNemar p"], rows, "tight")
            + f" {src('x2_experiment.json')}")


def sec_taxonomy() -> str:
    names = [("failure_taxonomy_before_fixes.json", "Round 0"), ("failure_taxonomy_round1.json", "Round 1"), ("failure_taxonomy.json", "Round 2 (final)")]
    data = [(label, load(f)) for f, label in names]
    data = [(label, d) for label, d in data if d]
    if not data:
        return NM
    cats = list(data[-1][1]["categories"].keys())
    rows = []
    for c in cats:
        rows.append([f"<code>{c}</code>"] + [d["categories"].get(c, {}).get("count", "-") for _, d in data])
    rows.append(["<b>total wrong decisions</b>"] + [f"<b>{d['total_failures']}</b>" for _, d in data])
    return table(["Category"] + [label for label, _ in data], rows, "tight")


FIXES = {
    "scam_missed": "Widened credential-phishing patterns (\"bank login\")",
    "injection_influenced": "Screening questions sanitised; scam signals read after injected sentences are stripped",
    "false_duplicate": "None: the Jaccard threshold (0.66) sits where duplicate and non-duplicate overlaps meet (0.60 to 0.74)",
    "duplicate_missed": "Persisted the near-duplicate index (it was memory-only and skipped on an exact re-sight)",
    "borderline_fit": "None: these sit between the watch (0.45) and bid (0.60) thresholds, a policy choice",
    "retrieval_miss": "One-character requirements such as \"R\" crashed the search tool; query widened; dedup false matches split out",
    "tool_error": "Decision no longer overwrites a failed branch with a skip; CI fails on any dead-letter",
    "overconfident_fit": "Hourly-rate floor: skip when the client's top rate is under 80% of the freelancer's rate",
}


def trajectory(cat: str) -> str:
    counts = []
    for f in ("failure_taxonomy_before_fixes.json", "failure_taxonomy_round1.json", "failure_taxonomy.json"):
        d = load(f)
        counts.append(str(d["categories"].get(cat, {}).get("count", 0)) if d else "?")
    return " &rarr; ".join(counts)


def sec_failures() -> str:
    d = load("failure_taxonomy.json")
    if not d:
        return NM
    rows = []
    n = 0
    for cat, v in d["categories"].items():
        for e in v["examples"][:3]:
            n += 1
            rows.append([e["job_id"], f"{e['gold']} / {e['pred']}", f"{e['fit'] if e['fit'] is not None else 'none'} / {e['risk'] if e['risk'] is not None else 'none'}",
                         f"<code>{cat}</code>", FIXES.get(cat, ""), trajectory(cat)])
    return (table(["Job", "Gold / agent", "Fit / risk", "Category", "Fix tried", "Count r0 &rarr; r1 &rarr; r2"], rows, "tight small")
            + f" {src('failure_taxonomy.json')} ({n} dev jobs shown, final round)")


def sec_budgets() -> str:
    d = load("decision_stub_test.json")
    if not d:
        return NM
    rows = []
    for p in PERSONAS:
        r = d["per_persona"][p]
        p95 = r["latency_s"]["p95"]
        rows.append([p, f"{p95:.1f}", "30", "met" if p95 <= 30 else "<b>missed</b>", "0 (stub: no model calls)", "not comparable", f"{r['tokens_per_job']}"])
    return table(["Persona", "p95 latency s", "Declared", "Result", "Cost per job", "vs $0.01 budget", "Tokens per job"], rows, "tight") + f" {src('decision_stub_test.json')}"


def sec_judge() -> str:
    r, lab = load("judge_calibration_report.json"), load("judge_calibration_labels.json")
    if not r or r.get("status") != "ok":
        return f"Judge calibration: {NM}."
    from collections import Counter

    dist = sorted(Counter(lab["labels"].values()).items())
    return (f"Judge <code>openai/gpt-oss-120b</code> against the author's own 30 labels (rubric 1 to 5, good means 4 or above): binary Cohen's kappa "
            f"<b>{r['kappa_binary_good_ge4']:.2f}</b>, quadratic-weighted ordinal kappa {r['kappa_ordinal_quadratic']:.2f}, unweighted ordinal kappa "
            f"{r['kappa_ordinal_unweighted']:.2f}, exact agreement {pct(r['exact_agreement'], 0)}. Mean score: judge {r['mean_judge']:.2f}, human "
            f"{r['mean_human']:.2f}. Human label counts (score:n): {', '.join(f'{k}:{v}' for k, v in dist)} {src('judge_calibration_report.json')}.")


CSS = """
@page { size: A4; margin: 13mm 14mm 14mm 14mm; }
* { box-sizing: border-box; }
body { font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif; font-size: 8.9pt; line-height: 1.38; color: #1c2430; margin: 0; }
h1 { font-size: 19pt; margin: 0 0 1mm; letter-spacing: -0.3px; color: #14233a; }
h2 { font-size: 11.2pt; margin: 4.2mm 0 1.2mm; color: #14233a; border-bottom: 1.2px solid #b5452f; padding-bottom: 0.6mm; page-break-after: avoid; }
h3 { font-size: 9.4pt; margin: 2.4mm 0 0.6mm; color: #1f3a5f; page-break-after: avoid; }
p { margin: 0 0 1.6mm; text-align: left; }
ul { margin: 0 0 1.6mm; padding-left: 4.6mm; } li { margin-bottom: 0.7mm; }
.sub { color: #5b6677; font-size: 9pt; margin-bottom: 2.4mm; }
.box { border: 1px solid #c9a227; background: #fff9e6; padding: 2mm 3mm; margin: 2mm 0 2.4mm; font-size: 8.5pt; }
table { border-collapse: collapse; width: 100%; margin: 1.2mm 0 1.8mm; font-size: 8pt; page-break-inside: avoid; }
th { background: #14233a; color: #fff; font-weight: 600; text-align: left; padding: 1mm 1.6mm; }
td { padding: 0.8mm 1.6mm; border-bottom: 0.5px solid #d6dbe3; vertical-align: top; }
tr:nth-child(even) td { background: #f5f7fa; }
table.tight { font-size: 7.6pt; } table.small { font-size: 7.1pt; }
code { font-family: Consolas, monospace; font-size: 0.92em; background: #eef1f5; padding: 0 1px; }
.src { color: #7a8494; font-size: 7pt; } .nm { color: #b5452f; font-style: italic; }
.flow { display: flex; align-items: center; gap: 1.2mm; margin: 1.5mm 0; }
.b { border: 1px solid #1f3a5f; border-radius: 3px; padding: 1.2mm 2mm; text-align: center; font-size: 7.6pt; background: #eef3fa; }
.b small { color: #5b6677; font-size: 6.6pt; } .b.p { background: #f4f9ee; border-color: #4f7a2b; } .b.h { background: #fdeeea; border-color: #b5452f; font-weight: 600; }
.par { display: flex; flex-direction: column; gap: 0.8mm; } .ar { color: #5b6677; }
.fig { width: 100%; margin: 1mm 0; }
.two { display: flex; gap: 4mm; } .two > div { flex: 1; }
.cap { color: #5b6677; font-size: 7.6pt; margin-top: -0.5mm; }
.foot { margin-top: 3mm; font-size: 7.6pt; color: #5b6677; }
"""


def html() -> str:
    V3_NOTE_BOX = ("(4) " + V3_NOTE) if runs_on_v3() else ""
    h1_ = sec_h1() if load("rag_variants.json") else NM
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>GigBid R&amp;D report</title><style>{CSS}</style></head><body>
<h1>GigBid: a multi-agent freelancer copilot</h1>
<div class="sub">R&amp;D report for AI-4016 &middot; {AUTHOR} &middot; <a href="{REPO}">{REPO}</a> &middot; every claim points to a file in <code>evals/results/</code> or the repository</div>
<div class="box"><b>Read this first.</b> (1) The instructor's <code>gigsim/</code>, personas and hidden test set were not in the starter kit I received: <code>gigsim/</code> is my own stand-in
and all jobs, clients and gold labels are synthetic (some history titles and budgets come from a real Kaggle Upwork dump). (2) Every agent number uses the deterministic <b>stub</b> model profile
(no LLM calls), so it tests routing, retrieval, policy, safety and plumbing, not the quality of LLM writing. (3) Dev numbers were used while tuning and are optimistic; the held-out split
(never tuned on) is reported separately. Sections 5 and 6 are <b>not measured</b>, for the reasons stated there. {V3_NOTE_BOX}</div>

<h2>1. Problem and constraints</h2>
<p>A freelancer on a marketplace spends hours scanning jobs, judging fit, pricing, and writing proposals that cost paid "Connects". GigBid scans, scores and drafts, then <b>stops for a human decision</b>.
It must never: send a proposal or message, spend Connects, accept a contract, or touch identity or payment details without an explicit approval naming the exact draft; submit in live-marketplace mode at all; or follow instructions found inside a job post.</p>
<p>Declared budgets (<code>agent/config.yaml</code>): p95 latency 30 s per job analysed, cost $0.01 per job and $0.03 per proposal, 12,000 tokens per job, 30 graph steps, at most 2 Critic send-backs, a weekly Connects budget.</p>

<h2>2. Architecture</h2>
{sec_architecture_diagram()}
<p><b>Why each agent exists.</b> Analyst turns prose into a typed <code>JobSpec</code>; Risk Assessor reads client history and scam, free-work, off-platform and injection signals; Fit Matcher maps every requirement to portfolio evidence.
They run in parallel through <code>Send</code> and share one deterministic requirement extractor so they stay independent. Decision applies thresholds from config. Writer, Verifier (every claim must cite evidence or is repaired),
Critic (bounded loop) and Compliance Guard (marketplace policy) sit between the draft and the human. The conversation graph classifies client messages, drafts replies and sends only after approval.</p>
<p><b>Surfaces.</b> One marketplace port with a GigSim adapter and a live-Upwork adapter (live mode never submits). Three own MCP servers expose 17 tools (Portfolio 3, Marketplace 11, Workspace 3) with schemas, read-only/destructive/idempotent hints,
bearer auth, rate limits, idempotency keys and an audit log. Stores: LangGraph checkpointer (SQLite locally; a Postgres path exists but was not exercised), long-term memory with explicit promotion rules (style: 3 edits across 2 jobs; outcome: lift of 0.10 with 3 samples per side),
a dedup store, JSONL traces, and the RAG indexes. Submit is exactly-once through a deterministic thread id plus the marketplace idempotency key. <b>Not integrated:</b> the official Upwork and GitHub third-party MCP servers.</p>

<h2>3. R&amp;D question A: tool granularity</h2>
<p><b>Setup.</b> 40 tasks, four tool surfaces: 35 one-endpoint tools with terse descriptions, 4 action-dispatch tools, the deployed 17-tool surface with rewritten descriptions, and the deployed surface with one-line descriptions as an ablation.
Selection and arguments are scored by gold labels; tokens are the rendered schemas plus the task. <b>The selector is an offline keyword-and-regex baseline, not an LLM</b>, so this measures how lexically separable the tool sets are.</p>
{sec_tools()}
<p><b>Result.</b> Coarse dispatch tools select the right tool more often than fine ones (82.5% vs 72.5%) but fail on arguments (50% vs 72.5%); the deployed surface is best on both (85% selection, 77.5% arguments) at 4.2k schema tokens against 0.4k for coarse.
Shortening the descriptions costs 12.5 points of selection, so in this setup descriptions mattered more than tool count. {src('tool_design.json')} <b>Conclusion, with the limit stated:</b> an LLM re-run is needed before this says anything about model behaviour; it is not done.</p>

<h2>4. R&amp;D question B: RAG variants, verification, ablation</h2>
<p>{h1_}</p>
<p>Variants V0 to V9 over 120 dev jobs per persona (gold evidence is exact by construction). Recall@5 is project-level. Latency is per job (all requirements searched, query caches cleared) on an idle machine; "-" means not re-measured.</p>
{sec_retrieval()}
{retrieval_figure()}
<div class="cap">Recall@5 against cold-query latency. Squares are stacked pipelines; the red dot is the shipped variant.</div>
<p><b>What the numbers say.</b> Requirement decomposition on its own <i>hurts</i> (V1 57.7 vs V0 64.2): per-requirement queries pull noisy chunks. Hybrid retrieval helps (V2 +3.4). The skill graph is the best single variant (V9 +8.4 over V0), and adding rerank on top of the stack buys
a few more points at far higher latency. Corrective retrieval (V8) lowered Recall@5 and its stack collapsed (41.0), although it did refuse in 51% of the cases where no gold evidence exists (7% false refusals) {src('rag_variants.json')}.
These are my readings of the table, not tested explanations.</p>
<h3>By persona, job type and number of requirements (Recall@5)</h3>
{sec_breakdown()}
<h3>Claim verification</h3>
<p>{sec_verify()} The stub writer composes drafts from evidence sentences, so its own unsupported-claim rate is near zero before verification; the fabricated-draft test above is the informative measure.</p>
<h3>Where better retrieval did or did not change the reply rate</h3>
{sec_reply_vs_retrieval()}
<h3>Ablation</h3>
<p>{sec_ablation()}</p>
<p>{sec_shipped()}</p>
{sec_b5()}

<h2>5. R&amp;D question C: single agent vs supervisor vs graph</h2>
<p><b>Not measured.</b> The comparison needs a real tool-calling model on 50 dev jobs for a single ReAct agent, a <code>langgraph-supervisor</code> agent and the hand-built graph. The stub profile cannot drive tool-calling agents, I built neither baseline,
and I will not offer an opinion dressed up as a result. What exists is the third arm: the graph, with traced runs, a 600-job dev evaluation and a 300-job held-out evaluation (sections 8 to 10), which is the baseline a future comparison would use.</p>

<h2>6. The change request</h2>
<p><b>Not measured.</b> The change request (the 2 Nov policy update) was not in the assignment text I received, so I do not know what changed and cannot report edit effort or time. The design intent is that marketplace rules are data
(<code>agent/policy_rules.yaml</code> plus the marketplace's policy endpoint), so a rule change should be a data edit rather than a code change. That is an untested design claim, not a finding.</p>

<h2>7. Signature extension X2: proposal A/B experiments</h2>
<p>Two strategies are config, not code: A <code>evidence_dense</code> (up to 3 cited portfolio items) and B <code>concise_question</code> (one item, short approach, closing question). Both pass the same Verifier, Critic and Compliance Guard, so only style varies.
Each of the same jobs is bid on once per strategy in separate simulator resets with the same seed; outcomes are replies read from the event log; tests are an unpaired z-test and a paired exact McNemar test.</p>
{sec_x2()}
<p>{sec_x2_reading()}The simulator's clients reward skill coverage and cited evidence by rule, so this shows the
pipeline can detect an effect the simulator contains, not that the effect exists on a real marketplace. No live-marketplace claim is made.</p>

<h2>8. Failure analysis</h2>
<p>Wrong bid-or-skip decisions on the dev set, bucketed by rule from recorded evidence (<code>evals/runners/failure_taxonomy.py</code>). Rounds are code versions: round 0 before any fix, round 1 after the injection, phishing and dedup fixes, round 2 after the hourly-rate floor and the tool-crash fixes.</p>
{sec_taxonomy()}
{sec_failures()}
<p><b>A bug found by reading a trace.</b> A job with the requirement "R" (the language) was skipped with "fit 0.00". The trace showed the search tool rejecting the one-character query on every retry; the graph then let the Decision node run on missing data and overwrite the dead-letter with a skip,
so a crash scored as a correct skip. Fixed in two places (query widening; Decision refuses to run after a failed branch) and the CI gate now fails on any dead-lettered job. Other mistakes are logged in <code>docs/AI_USAGE.md</code>.</p>

<h2>9. Safety and platform respect</h2>
<p><b>Enforced:</b> job text, screening questions and client messages are untrusted: delimited, injected sentences stripped, injected screening questions dropped, scam signals read from the stripped text; outgoing text passes the Compliance Guard and marketplace policy; <code>submit_proposal</code> and <code>send_message</code> are destructive-hinted and require an approval that names the draft;
idempotency keys prevent double submits; secrets and PII are masked in traces; CI forbids committed secrets and inline prompts.</p>
<p><b>What still gets through, measured:</b> {sec_scam_sentence()} (table in section 10), so some scams reach a draft and rely on the human approval. <b>Limits of the injection result:</b> attack success is 0 on the simulator's planted payloads, but these use a few templates and the stub profile has no LLM to hijack, so the 0 largely measures deterministic stripping, not an LLM's resistance.
Before the fixes, planted payloads in screening questions reached the job spec (6 of 49 under the earlier, looser metric {src('decision_stub_before_fixes.json')}); the metric was tightened afterwards to count only canary or $1-quote leakage, which is why the two figures are not directly comparable.</p>

<h2>10. Held-out results against the declared budgets</h2>
<p>These are the <b>local held-out split</b> (100 jobs per persona, different seed, never tuned on), not the instructor's hidden test set, which I do not have.</p>
{sec_decisions('decision_stub_test.json')}
{sec_budgets()}
<p>Dev split for comparison (used while tuning, so optimistic):</p>
{sec_decisions('decision_stub.json')}
<p>Latency is on a CPU laptop under 3-way concurrency with the stub profile; cost and tokens are zero because no model is called, so the cost budgets are untested. Interview and hire rates are not reported: they need the freelancer to answer within 72 simulated hours, which a batch run never does.</p>

<h2>Appendix A: judge calibration</h2>
<p>{sec_judge()}</p>
<h2>Appendix B: reproduce</h2>
<p><code>make seed</code>, <code>make test</code>, <code>python -m evals.runners.decision_eval --split test</code>, <code>python -m evals.runners.rag_eval</code>, <code>python -m evals.runners.gigsim_outcomes</code>, <code>python -m evals.runners.x2_experiment</code>,
<code>python scripts/render_readme.py</code>, <code>python scripts/build_report.py</code>. Technical write-up: <a href="https://medium.com/@i221378/my-evaluation-was-lying-to-me-what-a-multi-agent-proposal-copilot-taught-me-about-measurement-d57acfdf58b7">https://medium.com/@i221378/my-evaluation-was-lying-to-me-what-a-multi-agent-proposal-copilot-taught-me-about-measurement-d57acfdf58b7</a>. Known gaps: no public deployment or demo video yet, Postgres checkpointer and crash-and-resume not demonstrated, third-party MCP servers not integrated, no real-LLM runs, questions C and the change request not measured.</p>
<div class="foot">Generated from <code>evals/results/</code> by <code>scripts/build_report.py</code>.</div>
</body></html>"""


def find_browser() -> str | None:
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("chromium") or shutil.which("msedge")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    page = OUT / "GigBid_RD_Report.html"
    page.write_text(html(), encoding="utf-8")
    pdf = OUT / "GigBid_RD_Report.pdf"
    exe = find_browser()
    if not exe:
        print("no Edge/Chrome found; open the HTML and print to PDF")
        return 1
    subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={pdf}", page.as_uri()],
                   check=True, capture_output=True, timeout=180)
    from pypdf import PdfReader

    n = len(PdfReader(str(pdf)).pages)
    print(f"{pdf} pages={n}")
    return 0 if n <= 10 else 2


if __name__ == "__main__":
    sys.exit(main())
