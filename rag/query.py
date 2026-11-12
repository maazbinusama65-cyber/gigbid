"""Query-side helpers: job text, requirement extraction (V1), hypothetical proposal (V7).

Everything here is deterministic and offline. The two generators that benefit from an LLM
(requirement extraction is done by the Job Analyst node in the real graph; HyDE text) are
pluggable callables: pass ``hyde_fn`` / ``requirements`` explicitly to override.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from rag.text import split_sentences

HydeFn = Callable[[dict], str]
MAX_REQUIREMENTS = 8
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)")
_BOILERPLATE_RE = re.compile(
    r"^(hi|hello|dear|thanks|thank you|please|apply|looking forward|budget|deadline|"
    r"i am looking for a freelancer|we are a)\b", re.IGNORECASE)
_NEED_RE = re.compile(
    r"\b(need|needs|must|should|require|required|requires|looking|want|wants|build|create|"
    r"develop|implement|integrat|deploy|migrat|experience|expert|familiar|knowledge|support|"
    r"design|set up|setup|optimi[sz]e|automat|connect|train|analy[sz]e|scrape|write)\w*",
    re.IGNORECASE)


def job_title(job: dict) -> str:
    return str(job.get("title") or "")


def job_body(job: dict) -> str:
    """Free text of the job: description, or JobSpec deliverables/requirements."""
    if job.get("description"):
        return str(job["description"])
    parts = [*job.get("deliverables", []), *job.get("requirements", [])]
    return ". ".join(str(p) for p in parts)


def job_skills(job: dict) -> list[str]:
    return [str(s) for s in job.get("required_skills", [])]


def job_text(job: dict) -> str:
    """The 'whole job post' query used by V0: title + description + required skills."""
    parts = [job_title(job), job_body(job)]
    skills = job_skills(job)
    if skills:
        parts.append("Skills: " + ", ".join(skills))
    return "\n".join(p for p in parts if p).strip()


def extract_requirements(job: dict, max_n: int = MAX_REQUIREMENTS) -> list[str]:
    """Atomic requirements: explicit `requirements` if given, else bullets/sentences + skills."""
    explicit = [str(r).strip() for r in job.get("requirements", []) if str(r).strip()]
    if explicit:
        return explicit[:max_n]
    body = job_body(job)
    reqs: list[str] = []
    bullets = [m.group(1).strip() for ln in body.splitlines() if (m := _BULLET_RE.match(ln))]
    candidates = bullets or split_sentences(body)
    for sent in candidates:
        sent = sent.strip().rstrip(".")
        if len(sent.split()) < 4 or _BOILERPLATE_RE.match(sent):
            continue
        if bullets or _NEED_RE.search(sent):
            reqs.append(sent)
    seen_text = " ".join(reqs).lower()
    for skill in job_skills(job):
        if skill.lower() not in seen_text:
            reqs.append(f"experience with {skill}")
    if not reqs:
        title = job_title(job)
        reqs = [title] if title else []
    return list(dict.fromkeys(reqs))[:max_n]


def template_hyde(job: dict) -> str:
    """Default HyDE generator: a hypothetical ideal proposal paragraph (offline, template)."""
    reqs = extract_requirements(job, 4)
    skills = ", ".join(job_skills(job)[:6])
    did = "; ".join(r[0].lower() + r[1:] for r in reqs) or job_title(job)
    return (f"Thanks for posting {job_title(job)}. In a previous client project I delivered "
            f"{did}. I used {skills or 'the tools you mention'} and shipped a working, "
            f"documented solution with measurable results for a client in a similar industry.")


def single_requirement_job(requirement: str) -> dict:
    """Wrap one requirement as a job so `search(requirement)` reuses the job pipeline."""
    return {"title": "", "description": requirement, "requirements": [requirement],
            "required_skills": []}
