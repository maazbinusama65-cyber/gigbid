"""Past proposals (~150 per persona) with outcomes driven by real features of the text.

Features that raise reply/win odds: evidence-citing body (names a real project + a metric),
non-generic opening, price under the client's ceiling. Overclaiming ("guarantee 100%") lowers them.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta

from . import jobtext
from .catalog_skills import CATEGORIES, SKILLS
from .docs_gen import NAME_TO_ID

GENERIC_OPENINGS = [
    "Hello, I am writing to express my interest in your job posting.",
    "Dear Sir/Madam, I am a hardworking professional and I am very interested in this job.",
    "Hi, I have read your job description and I think I am a good fit.",
    "Greetings! I am an experienced freelancer with many years of experience in various technologies.",
    "I am excited to apply for this position. I can do this job perfectly.",
    "Hello there, I saw your post and I am the right person for you.",
]
VAGUE_BODIES = [
    "I have worked with a wide range of technologies for many years and can start immediately. Quality is my top priority.",
    "I am a fast learner and a team player with strong communication skills. I have completed many projects for happy clients.",
    "I can handle everything you listed and more. Please check my profile for my experience.",
]
OVERCLAIMS = ["I guarantee 100% satisfaction and perfect results.", "I guarantee guaranteed delivery with zero bugs."]
SPECIFIC_OPENINGS = [
    "Your point about {req} is close to something I shipped for a {ind} client.",
    "{Req} is the part of your post I would worry about first, and I have done it before for a {ind} team.",
    "I read your brief twice: {req}. I solved that for a {ind} company last year.",
]
GOOD_CLOSERS = ["Would you rather I start with a one-page plan or with a working prototype? I can share either within two days.",
                "If useful, I can send a short outline of how I would sequence the first week before you decide."]
BAD_CLOSERS = ["Looking forward to hearing from you. Thanks.", "Please contact me. Thank you for your time."]


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _evidence(rng: random.Random, proj: dict) -> str:
    named = [SKILLS[NAME_TO_ID[n]].name for n in proj["skills"][:2]]
    imp = SKILLS[NAME_TO_ID[proj["skills"][-1]]].implied[0]
    ref = rng.choice(proj["aliases"])
    return (f"On {proj['title']} (what the client called a {ref}) {proj['problem']}. I built it with "
            f"{' and '.join(named)}, plus {imp}. Result: {proj['outcome_summary']}.")


def generate(persona_id: str, ctx, rng: random.Random, n: int = 150) -> list[dict]:
    out = []
    rate = ctx.profile["hourly_rate_usd"]
    for i in range(n):
        proj = rng.choice(ctx.core)
        psids = [NAME_TO_ID[s] for s in proj["skills"]]
        req_sid = rng.choice(psids)
        theme = rng.choice(proj["aliases"])
        title = jobtext.title(rng, [req_sid], SKILLS[req_sid].category, proj["industry"], theme if rng.random() < 0.6 else None)
        E, good_open, under = rng.random() < 0.45, rng.random() < 0.55, rng.random() < 0.6
        over_claim = (not E) and rng.random() < 0.2
        ind = proj["industry"] if rng.random() < 0.75 else rng.choice(jobtext.INDUSTRIES)
        parts, cited = [], []
        if good_open:
            req = rng.choice(SKILLS[req_sid].implied)
            parts.append(rng.choice(SPECIFIC_OPENINGS).format(req=req, Req=req[0].upper() + req[1:], ind=ind.lower()))
        else:
            parts.append(rng.choice(GENERIC_OPENINGS))
        if E:
            parts.append(_evidence(rng, proj))
            cited.append(proj["project_id"])
            if rng.random() < 0.3:
                other = rng.choice([p for p in ctx.core if p is not proj])
                parts.append(f"A second relevant piece of work: {other['title']}, where {other['outcome_summary']}.")
                cited.append(other["project_id"])
        else:
            parts.append(rng.choice(VAGUE_BODIES))
            if over_claim:
                parts.append(rng.choice(OVERCLAIMS))
        fair_mid = jobtext_fair_mid(psids, rate)
        ceiling = fair_mid * rng.uniform(0.9, 1.4)
        bid = ceiling * (rng.uniform(0.75, 0.98) if under else rng.uniform(1.1, 1.6))
        parts.append(f"My fixed price for this is ${int(round(bid, -1))}.")
        parts.append(rng.choice(GOOD_CLOSERS if good_open and E else BAD_CLOSERS))
        logit = -3.1 + 1.7 * E + 1.3 * good_open + 1.0 * under - 1.5 * over_claim + rng.gauss(0, 0.4)
        replied = rng.random() < _sigmoid(logit)
        won = replied and rng.random() < _sigmoid(-1.6 + 1.0 * E + 0.8 * under)
        d = date(2022, 1, 10) + timedelta(days=rng.randint(0, 1130))
        out.append({"proposal_id": f"pp-{persona_id}-{i + 1:03d}", "job_title": title, "text": "\n\n".join(parts),
                    "outcome": "won" if won else "replied" if replied else "ignored", "date": d.isoformat(),
                    "project_ids": cited, "client_industry": ind,
                    "category": CATEGORIES[ctx.profile["primary_category"]]})
    return out


def jobtext_fair_mid(sids, rate: int) -> float:
    from .jobgen import hours_for
    return hours_for(sids) * rate * 1.05
