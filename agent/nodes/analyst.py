"""Job Analyst: structured JobSpec (heuristic baseline, optionally refined by a small LLM)."""
from __future__ import annotations

import re

from agent.guardrails import strip_injection, wrap_untrusted
from agent.handoffs import Budget, JobSpec
from agent.nodes.common import Ctx, first_sentences
from agent.prompts import load_prompt

_HIDDEN_HINTS = {
    r"reproducib": "reproducible, documented work",
    r"document": "clear documentation / handover",
    r"deploy|production|docker|ci/?cd": "production-ready delivery",
    r"deadline|asap|urgent": "tight timeline sensitivity",
    r"communicat|update|weekly": "regular communication",
    r"test": "automated tests",
    r"scal": "scalability concerns",
}


def extract_requirements(job: dict, max_n: int = 7) -> list[str]:
    """Deterministic requirement extraction shared by Analyst and Fit Matcher (they run in parallel)."""
    reqs = [s for s in job.get("required_skills", []) if s]
    desc = strip_injection(job.get("description", ""))
    for line in re.split(r"[\n;]|(?<=[.!?])\s+", desc):
        line = line.strip(" -*•")
        if re.search(r"\b(need|require|must|experience (with|in)|build|create|implement|design|migrate|integrate)\b", line, re.I):
            if 12 < len(line) < 140 and line not in reqs:
                reqs.append(line)
    return reqs[:max_n]


def heuristic_spec(job: dict) -> JobSpec:
    desc = strip_injection(job.get("description", ""))
    b = job.get("budget") or {}
    hidden = [h for pat, h in _HIDDEN_HINTS.items() if re.search(pat, desc, re.I)]
    deliverables = [first_sentences(desc, 1, 140)] if desc else []
    return JobSpec(
        job_id=job["job_id"], title=job.get("title", ""), deliverables=[d for d in deliverables if d],
        required_skills=list(job.get("required_skills", [])), requirements=extract_requirements(job),
        budget=Budget(type=b.get("type", "fixed"), min=b.get("min"), max=b.get("max"), currency=b.get("currency", "USD")),
        budget_min=b.get("min"), budget_max=b.get("max"), timeline_days=job.get("duration_days"),
        screening_questions=list(job.get("screening_questions", [])), hidden_needs=hidden,
        category=job.get("category", "general"),
    )


async def analyst(state: dict, ctx: Ctx) -> dict:
    job = state["job"]
    spec = heuristic_spec(job)
    if ctx.use_llm("analyst"):
        _, system = load_prompt("analyst")
        safe_post = strip_injection(f"{job.get('title','')}\n{job.get('description','')}")
        res = await ctx.llm.chat(
            "analyst", system,
            wrap_untrusted(safe_post) + f"\nrequired_skills={job.get('required_skills')}\njob_id={job['job_id']}",
            schema=JobSpec, max_tokens=700)
        if res.parsed is not None:
            llm_spec: JobSpec = res.parsed
            # deterministic fields stay authoritative; take the LLM's richer text fields
            spec.deliverables = llm_spec.deliverables or spec.deliverables
            spec.hidden_needs = llm_spec.hidden_needs or spec.hidden_needs
            extra = [r for r in llm_spec.requirements if r not in spec.requirements]
            spec.requirements = (spec.requirements + extra)[:7]
    return {"job_spec": spec.model_dump()}
