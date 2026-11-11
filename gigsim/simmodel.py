"""Rule-based simulated clients: hidden preferences + deterministic seeded decisions.

Hidden per (client, job): must-have skills (subset of the job's required skills), a budget ceiling
and a dislike of generic openings. They are re-derived from the seed on demand and never exposed
through the API. A decision plan is fixed at submit time from (seed, freelancer, job, proposal
text), so the outcome does not depend on how ticks are chunked.
"""
from __future__ import annotations

import hashlib
import math
import random
import re

from .catalog_skills import SKILLS

HOUR = 3600
WEEK = 7 * 24 * HOUR
STOP = {"with", "that", "from", "this", "into", "over", "have", "your", "them", "their", "and", "the", "for", "are"}
NAME_TO_ID = {s.name.lower(): s.id for s in SKILLS.values()}

GENERIC_OPENING = re.compile(
    r"^\s*(hello|hi|dear|greetings|good (morning|day))[^.!?]{0,40}[,!.]?\s*(i am writing to|i am interested|i have read|"
    r"i saw your|i am (a |an )?(hardworking|experienced|excited)|i am the right|sir|madam)|"
    r"i am writing to express|i am excited to apply|i can do this job|i am a hardworking|"
    r"i am the right person|i think i am a good fit|many years of experience in various", re.I)
FORBIDDEN = re.compile(r"\bguarantee[sd]?\b|100% (satisfaction|results|accuracy|success)|whatsapp|telegram|skype|"
                       r"outside (of )?(the )?platform|off[- ]platform|paypal me|zero bugs", re.I)
EVIDENCE = re.compile(r"\d+(\.\d+)?\s?%|\b\d{2,}[\d,]*\s*(ms|seconds|hours|days|users|invoices|products|articles|"
                      r"customers|tickets|calls|events|accounts|skus|x)\b|\b(shipped|delivered|i built|i solved|"
                      r"for a [a-z\- ]+ client|case study|previous project|last year)\b", re.I)


def rng_for(*parts) -> random.Random:
    return random.Random(":".join(str(p) for p in parts))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def _toks(phrase: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{5,}", phrase.lower()) if w not in STOP}


def mentions_skill(text_lc: str, tokens: set[str], skill_id: str) -> bool:
    sk = SKILLS[skill_id]
    name = sk.name.lower()
    pat = r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])"
    if re.search(pat, text_lc):
        return True
    for phrase in sk.implied:
        want = _toks(phrase)
        if len(want) >= 2 and len(want & tokens) >= max(2, math.ceil(0.6 * len(want))):
            return True
    return False


def client_prefs(seed: int, job: dict) -> dict:
    """Hidden preferences of the job's client (deterministic in seed, client, job)."""
    rng = rng_for(seed, "prefs", job["client_id"], job["job_id"])
    sids = [NAME_TO_ID[n.lower()] for n in job.get("required_skills", []) if n.lower() in NAME_TO_ID]
    rng.shuffle(sids)
    k = max(1, round(len(sids) * 0.6)) if sids else 0
    b = job.get("budget") or {}
    ceiling = float(b.get("max") or 0) * rng.uniform(0.95, 1.25)
    return {"must_have": sids[:k], "ceiling": ceiling, "generic_dislike": rng.uniform(0.6, 1.0),
            "noise": rng.gauss(0, 0.25), "bias": rng.uniform(-0.2, 0.2)}


def features(prefs: dict, job: dict, cover_letter: str, answers: list[str], bid: float) -> dict:
    text = cover_letter or ""
    lc = text.lower()
    tokens = set(re.findall(r"[a-z]{5,}", lc))
    must = prefs["must_have"]
    hit = [s for s in must if mentions_skill(lc, tokens, s)]
    words = len(text.split())
    qs = job.get("screening_questions") or []
    answered = bool(qs) and len([a for a in answers if str(a).strip()]) >= len(qs)
    r = (bid / prefs["ceiling"]) if prefs["ceiling"] > 0 else 1.0
    return {"skill_cov": (len(hit) / len(must)) if must else 0.5, "evidence": 1.0 if EVIDENCE.search(text) else 0.0,
            "generic": bool(GENERIC_OPENING.search(text[:220])), "forbidden": bool(FORBIDDEN.search(text + " " + " ".join(map(str, answers)))),
            "answered": answered, "unanswered": bool(qs) and not answered, "price_ratio": r, "words": words,
            "hit": hit}


def probabilities(prefs: dict, f: dict) -> dict:
    logit = -2.3 + 2.6 * f["skill_cov"] + 0.9 * f["evidence"] + prefs["bias"] + prefs["noise"]
    logit += 0.4 if f["answered"] else (-0.6 if f["unanswered"] else 0.0)
    logit -= 1.4 * prefs["generic_dislike"] if f["generic"] else 0.0
    logit -= 3.0 if f["forbidden"] else 0.0
    r = f["price_ratio"]
    logit += 0.5 if r <= 0.95 else -min(3.0, 5.0 * (r - 1.0)) if r > 1.0 else 0.0
    logit -= 0.8 if f["words"] < 40 else (0.5 if f["words"] > 400 else 0.0)
    s = f["skill_cov"]
    return {"view": 0.4 if f["forbidden"] else 0.88, "reply": sigmoid(logit),
            "interview": sigmoid(-0.2 + 1.5 * s + 0.3 * f["evidence"]),
            "hire": sigmoid(-0.6 + 1.2 * s + (0.6 if r <= 1 else -0.8))}


def make_plan(seed: int, fid: str, job: dict, cover_letter: str, answers: list[str], bid: float, hook=None) -> dict:
    prefs = client_prefs(seed, job)
    f = features(prefs, job, cover_letter, answers, bid)
    p = probabilities(prefs, f)
    if hook is not None:
        p = hook(prefs, f, dict(p)) or p
    h = hashlib.sha256(cover_letter.encode()).hexdigest()[:12]
    rng = rng_for(seed, "plan", fid, job["job_id"], h)
    plan = {"will_view": rng.random() < p["view"], "will_reply": rng.random() < p["reply"],
            "will_interview": rng.random() < p["interview"], "will_hire": rng.random() < p["hire"],
            "view_delay": int((1 + rng.expovariate(1 / 10)) * HOUR), "reply_delay": int((2 + rng.expovariate(1 / 14)) * HOUR),
            "int_delay": int((4 + rng.expovariate(1 / 20)) * HOUR), "hire_delay": int((24 + rng.expovariate(1 / 48)) * HOUR),
            "lost_delay": int((36 + rng.random() * 36) * HOUR), "silence_delay": int((72 + rng.random() * 96) * HOUR),
            "must_have": [SKILLS[s].name for s in prefs["must_have"]], "probs": {k: round(v, 4) for k, v in p.items()},
            "features": {k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items() if k != "hit"}}
    return plan


REPLY_WAIT = 72 * HOUR


def advance(prop: dict, plan: dict, fl_msg_ts: list[int], now: int) -> list[tuple[int, str]]:
    """Fire every due transition of one proposal up to `now` (epoch seconds, simulated). Mutates prop."""
    out: list[tuple[int, str]] = []
    while True:
        st, t0 = prop["status"], prop["status_ts"]
        if st == "submitted":
            due, new = ((t0 + plan["view_delay"], "viewed") if plan["will_view"] else (t0 + plan["silence_delay"], "lost"))
        elif st == "viewed":
            due, new = ((t0 + plan["reply_delay"], "replied") if plan["will_reply"] else (t0 + plan["lost_delay"], "lost"))
        elif st == "replied":
            msgs = [m for m in fl_msg_ts if m >= t0]
            deadline = t0 + REPLY_WAIT
            if msgs and msgs[0] <= deadline:
                due, new = msgs[0] + plan["int_delay"], ("interview" if plan["will_interview"] else "lost")
            elif now >= deadline:
                due, new = deadline, "lost"
            else:
                break
        elif st == "interview":
            due, new = t0 + plan["hire_delay"], ("hired" if plan["will_hire"] else "lost")
        else:
            break
        if due > now:
            break
        prop["status"], prop["status_ts"] = new, due
        out.append((due, new))
    return out


def client_message(kind: str, job: dict, plan: dict) -> str:
    must = plan["must_have"][0] if plan["must_have"] else "this kind of work"
    return {
        "replied": f"Thanks for your proposal for \"{job['title']}\". Could you tell me more about your experience with {must}? "
                   "Are you available for a short call this week?",
        "interview": "Great, let's set up a call. Please send two or three time slots that work for you.",
        "hired": "We would like to hire you. I am sending the offer now.",
        "lost": "Thank you for your time, but we have decided to go in a different direction.",
    }[kind]


def auto_reply(text: str) -> str:
    if FORBIDDEN.search(text):
        return "Please keep all communication and payments on the platform."
    if re.search(r"\b(slot|available|availability|call|tomorrow|monday|tuesday|wednesday|thursday|friday)\b", text, re.I):
        return "Thanks, that works for us. We will confirm shortly."
    return "Thanks for the update, noted."
