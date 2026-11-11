"""Persona corpus documents: case studies, repo READMEs + code, reviews, CV (md + pdf).

The corpus is built to defeat naive RAG: each project is described several different ways, with
different vocabulary (title / aliases), different skill *names* (a skill is named in one document
and only implied in another), and code mixed with prose.
"""
from __future__ import annotations

import random
import re
from pathlib import Path

from .catalog_skills import SKILLS

NAME_TO_ID = {s.name: s.id for s in SKILLS.values()}
VERBS = ["run", "handle", "build", "score", "load", "sync", "check", "route"]


def pkg_name(slug: str) -> str:
    return slug.replace("-", "_")


def camel(slug: str) -> str:
    return "".join(p.capitalize() for p in slug.split("-"))


def skill_ids(project: dict) -> list[str]:
    return [NAME_TO_ID[n] for n in project["skills"]]


def render_code(skill_id: str, project: dict, rng: random.Random) -> tuple[str, str, str] | None:
    sk = SKILLS[skill_id]
    if not sk.code:
        return None
    verb = VERBS[rng.randrange(len(VERBS))]
    noun = pkg_name(project["project_id"]).split("_")[0]
    fn = f"{verb}_{noun}"
    if sk.lang in ("ts", "js"):
        fn = verb + noun.capitalize()
    text = (sk.code.replace("__PKG__", pkg_name(project["project_id"]))
            .replace("__FN__", fn).replace("__CLS__", camel(project["project_id"]) + "Item"))
    ext = {"py": "py", "ts": "ts", "sql": "sql", "yaml": "yml", "r": "R", "js": "gs", "dockerfile": ""}[sk.lang]
    if sk.lang == "ts" and ("<div" in text or "<button" in text or "<pre" in text):
        ext = "tsx"
    fname = "Dockerfile" if sk.lang == "dockerfile" else f"{skill_id}_{noun}.{ext}"
    return fname, text, sk.lang


def _modes(project: dict, rng: random.Random) -> dict[str, tuple[bool, bool]]:
    """skill id -> (named_in_case_study, named_in_readme)."""
    out = {}
    for sid in skill_ids(project):
        r = rng.random()
        out[sid] = ((True, False) if r < 0.35 else (False, True) if r < 0.70
                    else (True, True) if r < 0.80 else (False, False))
    return out


NAMED = ["I used {n} for this part.", "{n} did the heavy lifting here.", "The stack included {n}.",
         "Under the hood: {n}.", "This is where {n} came in."]
IMPLIED = ["On the engineering side I put in place {i}.", "It relied on {i}.",
           "I set up {i}.", "A key piece was {i}.", "We ended up with {i}."]


def _sentence(sid: str, named: bool, rng: random.Random) -> str:
    sk = SKILLS[sid]
    if named:
        return rng.choice(NAMED).format(n=sk.name)
    return rng.choice(IMPLIED).format(i=sk.implied[rng.randrange(len(sk.implied))])


def case_study(project: dict, rng: random.Random, modes: dict) -> str:
    sids = skill_ids(project)
    when = project["date"][:7]
    lines = [f"# {project['title']}", "",
             f"**Client industry:** {project['industry']}  ", f"**Completed:** {when}  ",
             "**Role:** sole engineer, from first call to hand-over", "",
             "## The problem", "", f"The client had a familiar pain: {project['problem']}. "
             f"They described what they wanted as a {project['aliases'][0]}.", "",
             "## What I built", ""]
    for sid in sids:
        lines.append(_sentence(sid, modes[sid][0], rng))
    lines += ["", "## Outcome", "", f"Result: {project['outcome_summary']}.", ""]
    named = [SKILLS[s].name for s in sids if modes[s][0]]
    if named and rng.random() < 0.7:
        lines += ["## Stack", "", ", ".join(named), ""]
    if rng.random() < 0.35:
        for sid in sids:
            rc = render_code(sid, project, rng)
            if rc and rc[2] in ("py", "sql", "ts"):
                lines += ["## A snippet", "", f"```{rc[2]}", rc[1], "```", ""]
                break
    return "\n".join(lines)


def readme(project: dict, rng: random.Random, modes: dict, files: list[str]) -> str:
    sids = skill_ids(project)
    lines = [f"# {project['project_id']}", "", f"> {project['aliases'][1]} - repository for the "
             f"{project['industry'].lower()} engagement.", "", "## Features", ""]
    for sid in sids:
        sk = SKILLS[sid]
        if modes[sid][1]:
            lines.append(f"- Uses **{sk.name}** (see `src/`)")
        else:
            imp = sk.implied[rng.randrange(len(sk.implied))]
            lines.append(f"- {imp[0].upper() + imp[1:]}")
    lines += ["", "## Quick start", "", "```bash"]
    if any(SKILLS[s].lang == "ts" for s in sids):
        lines += ["npm install", "npm run dev"]
    else:
        lines += ["python -m venv .venv && . .venv/bin/activate", "pip install -r requirements.txt",
                  "python -m src.main"]
    lines += ["```", ""]
    if files:
        lines += ["## Layout", ""] + [f"- `src/{f}`" for f in files] + [""]
    lines += ["## Status", "", "Delivered and handed over; this repository is the frozen client copy.", ""]
    return "\n".join(lines)


def write_repo(root: Path, project: dict, rng: random.Random, modes: dict) -> None:
    repo = root / "repos" / project["project_id"]
    (repo / "src").mkdir(parents=True, exist_ok=True)
    files = []
    seen = set()
    for sid in skill_ids(project):
        if len(files) >= 3:
            break
        rc = render_code(sid, project, rng)
        if rc and rc[0] not in seen:
            seen.add(rc[0])
            (repo / "src" / rc[0]).write_text(rc[1] + "\n", encoding="utf-8")
            files.append(rc[0])
    (repo / "README.md").write_text(readme(project, rng, modes, files), encoding="utf-8")


REVIEW_OPENERS = ["Great to work with.", "Delivered what we hoped for.", "Calm, clear and quick.",
                  "Would hire again.", "Exactly the help we needed.", "Solid communication throughout."]
REVIEW_BODIES = [
    "We came in wanting {a}; the end result changed how the team works. {o}",
    "Our problem was simple to state: {p}. Afterwards: {o}",
    "I am not technical, but I could always tell where things stood. {o}",
    "Delivered {a} ahead of the date we agreed. {o}",
]


def reviews(persona: str, projects: list[dict], rng: random.Random) -> list[dict]:
    out = []
    for p in projects:
        if p["kind"] != "core":
            n = 1 if rng.random() < 0.6 else 0
        else:
            n = 1 + (rng.random() < 0.55)
        for _ in range(n):
            rating = 5 if rng.random() < 0.72 else (4 if rng.random() < 0.8 else 3)
            body = rng.choice(REVIEW_BODIES).format(a=p["aliases"][rng.randrange(2)], p=p["problem"],
                                                    o=_qual(p["outcome_summary"]))
            y, m, _d = p["date"].split("-")
            mm = min(12, int(m) + rng.randint(1, 2))
            out.append(dict(review_id=f"rev-{persona}-{len(out) + 1:03d}", project_id=p["project_id"],
                            client_industry=p["industry"], rating=rating,
                            text=f"{rng.choice(REVIEW_OPENERS)} {body}", date=f"{y}-{mm:02d}-{rng.randint(1, 28):02d}"))
    return out


def _qual(outcome: str) -> str:
    """Business-language rewrite: strip tool-ish detail, keep the outcome (different vocabulary)."""
    s = re.sub(r"\b(p9\d|p95|WAPE|MAPE|ROUGE-L|LCP)\b[^;,]*", "", outcome)
    return "Overall: " + s.strip().rstrip(".") + "."


def cv_blocks(persona: str, prof: dict, projects: list[dict], rng: random.Random) -> list[tuple[str, str]]:
    blocks = [("h1", prof["display_name"]), ("p", prof["headline"]),
              ("p", f"Rate: ${prof['hourly_rate_usd']}/h  |  Availability: {prof['availability_hours_per_week']} h/week  |  Remote, worldwide"),
              ("h2", "Summary"),
              ("p", "Independent freelancer delivering production work for small and mid-size teams. "
                    "Comfortable owning a project from the first call to hand-over, and explicit about scope and price."),
              ("h2", "Skills"), ("p", ", ".join(prof["skills"])), ("h2", "Selected experience")]
    core = sorted((p for p in projects if p["kind"] == "core"), key=lambda p: p["date"], reverse=True)
    for p in core[:12]:
        names = [s for s in p["skills"] if rng.random() < 0.5][:2]
        tail = f" ({', '.join(names)})" if names else ""
        blocks.append(("b", f"{p['date'][:4]} - Delivered {p['aliases'][rng.randrange(2)]} for a "
                            f"{p['industry'].lower()} client{tail}. Impact: {p['outcome_summary']}."))
    blocks += [("h2", "Education"), ("p", "B.S. Computer Science (synthetic persona)"),
               ("h2", "Languages"), ("p", "English (fluent)")]
    return blocks


def cv_markdown(blocks) -> str:
    out = []
    for kind, text in blocks:
        out.append({"h1": f"# {text}", "h2": f"## {text}", "b": f"- {text}", "p": text}[kind])
        if kind != "b":
            out.append("")
    return "\n".join(out).replace("\n\n- ", "\n- ") + "\n"


def cv_pdf(blocks, path: Path) -> None:
    from reportlab import rl_config
    rl_config.invariant = 1
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    ss = getSampleStyleSheet()
    style = {"h1": ss["Title"], "h2": ss["Heading2"], "p": ss["BodyText"], "b": ss["BodyText"]}
    flow = []
    for kind, text in blocks:
        flow.append(Paragraph(("&bull; " if kind == "b" else "") + escape(text), style[kind]))
        flow.append(Spacer(1, 4))
    SimpleDocTemplate(str(path), pagesize=A4, title=blocks[0][1], author="synthetic", invariant=1).build(flow)
