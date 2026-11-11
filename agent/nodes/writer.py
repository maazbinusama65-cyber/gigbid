"""Proposal Writer: cover letter + screening answers, every claim cites portfolio evidence."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from agent.guardrails import strip_injection, wrap_untrusted
from agent.handoffs import ProposalDraft
from agent.nodes.common import Ctx, first_sentences
from agent.prompts import load_prompt


class WriterOut(BaseModel):
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


def _select_evidence(state: dict, limit: int = 6) -> list[dict]:
    ev = {e["id"]: e for e in state.get("evidence", [])}
    ordered: list[dict] = []
    for m in state.get("fit_report", {}).get("matrix", []):
        for i in m.get("evidence_ids", []):
            if i in ev and ev[i] not in ordered:
                ordered.append(ev[i])
    for e in sorted(ev.values(), key=lambda e: -e.get("score", 0)):
        if e not in ordered:
            ordered.append(e)
    return ordered[:limit]


def _style_flags(rules: list[str]) -> dict:
    j = " ".join(rules).lower()
    return {"drop_opening": "generic first sentence" in j, "shorter": "shorter" in j,
            "end_question": "specific question" in j,
            "avoid": [m for m in re.findall(r"phrase '([^']+)'", j)]}


def _claim_sentence(ev: dict, max_chars: int = 220) -> str:
    base = first_sentences(ev.get("text", ""), 1, max_chars) or ev.get("title", "")
    return base.rstrip(".") + "."


def _compose(state: dict, evidence: list[dict], style: dict, feedback: list[str]) -> WriterOut:
    job, spec = state["job"], state.get("job_spec", {})
    matrix = state.get("fit_report", {}).get("matrix", [])
    ev_by_id = {e["id"]: e for e in evidence}
    parts: list[str] = []
    used: list[str] = []
    top_req = next((m["requirement"] for m in matrix if m.get("evidence_ids")), (spec.get("required_skills") or ["this"])[0])
    if not style["drop_opening"]:
        parts.append(f"The core of \"{job.get('title','your project')}\" is {top_req}, so that is where I would start.")
    variant = (state.get("settings") or {}).get("style_variant", "evidence_dense")
    per_req = {"concise_question": 0}.get(variant, 1 if style["shorter"] else 2)   # evidence sentences - 1
    for m in matrix:
        for i in m.get("evidence_ids", [])[:2]:
            if i in ev_by_id and i not in used and len(used) < per_req + 1:
                parts.append(f"On {m['requirement']}: {_claim_sentence(ev_by_id[i])} [{i}]")
                used.append(i)
    if variant == "concise_question":
        parts.append("My approach: start with the simplest version that answers your question, then iterate on "
                     "what the first results show.")
    missing = [m["requirement"] for m in matrix if m.get("strength", 0) < 0.4 and len(m["requirement"]) <= 40][:2]
    if missing:
        parts.append(f"I have not shipped {' or '.join(missing)} in a client project, so I would flag it early and "
                     f"scope a small spike before committing.")
    if style["end_question"] or not style["drop_opening"]:
        parts.append(f"Which part of {top_req} matters most for your first milestone?")
    letter = " ".join(parts)
    for ph in style["avoid"]:
        letter = re.sub(re.escape(ph), "", letter, flags=re.I)
    answers: list[str] = []
    for q in job.get("screening_questions", []):
        qt = set(re.findall(r"[a-z0-9]+", q.lower()))
        best = max(evidence, key=lambda e: len(qt & set(re.findall(r"[a-z0-9]+", (e.get('text','') + ' ' + e.get('title','')).lower()))), default=None)
        if best and len(qt & set(re.findall(r"[a-z0-9]+", best.get("text", "").lower()))) >= 2:
            answers.append(f"{_claim_sentence(best, 240)} [{best['id']}]")
            used.append(best["id"])
        else:
            answers.append("I would start by clarifying the success metric and data available, then propose a small "
                           "first milestone you can evaluate before we continue.")
    if feedback:
        letter = letter  # deterministic composer already follows the same rules; feedback is logged in the trace
    return WriterOut(cover_letter=letter.strip(), screening_answers=answers, evidence_ids=list(dict.fromkeys(used)))


async def writer(state: dict, ctx: Ctx) -> dict:
    uid = state.get("user_id", "anon")
    evidence = _select_evidence(state)
    style_rules = ctx.memory.style_rules(uid)
    cat = (state.get("job_spec") or {}).get("category", state["job"].get("category", ""))
    hints = ctx.memory.outcome_hints(uid, cat)
    critiques = state.get("critiques", [])
    feedback = critiques[-1].get("issues", []) if critiques and critiques[-1].get("send_back") else []
    revision = int(state.get("revision", 0)) + (1 if feedback else 0)
    out: WriterOut | None = None
    if ctx.use_llm("writer"):
        _, system = load_prompt("writer")
        ev_txt = "\n".join(f"[{e['id']}] ({e['type']}, project={e.get('project_id')}, outcome={e.get('outcome')}) "
                           f"{e.get('text','')[:600]}" for e in evidence)
        job = state["job"]
        user = (wrap_untrusted(strip_injection(f"{job.get('title','')}\n{job.get('description','')}")) +
                f"\n\nREQUIREMENTS: {state.get('job_spec', {}).get('requirements')}\n"
                f"SCREENING QUESTIONS: {job.get('screening_questions')}\n\nEVIDENCE:\n{ev_txt}\n\n"
                f"STYLE RULES: {style_rules or 'none'}\nOUTCOME HINTS: {hints or 'none'}\n"
                f"STRATEGY: {(state.get('settings') or {}).get('style_variant', 'evidence_dense')}\n"
                f"FIX THESE ISSUES FROM THE CRITIC: {feedback or 'none'}")
        res = await ctx.llm.chat("writer", system, user, schema=WriterOut, max_tokens=900, temperature=0.4)
        out = res.parsed
    if out is None:
        out = _compose(state, evidence, _style_flags(style_rules), feedback)
    known = {e["id"] for e in evidence}
    in_text = re.findall(r"\[([^\]\s]+)\]", out.cover_letter + " " + " ".join(out.screening_answers))
    cited = [i for i in dict.fromkeys(out.evidence_ids + in_text) if i in known]
    draft = ProposalDraft(job_id=state["job_id"], cover_letter=out.cover_letter,
                          screening_answers=out.screening_answers, evidence_ids=cited, revision=revision)
    return {"proposal_draft": draft.model_dump(), "revision": revision, "evidence": evidence}
