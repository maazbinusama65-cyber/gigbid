"""Client pool, history jobs (synthetic + optional real titles/budgets) and pricing statistics."""
from __future__ import annotations

import html
import random
from datetime import UTC, datetime, timedelta

from . import jobgen, jobtext
from .catalog_skills import CATEGORIES, SKILLS

NAME_A = ["Bright", "North", "Blue", "Summit", "Clear", "Iron", "Maple", "Nova", "Pine", "Stone", "Swift",
          "Harbor", "Lumen", "Cedar", "Atlas", "Orbit", "River", "Quartz", "Vista", "Willow"]
NAME_B = ["path", "wave", "works", "loop", "forge", "yard", "line", "grid", "hub", "labs", "point", "craft"]
NAME_C = ["Logistics", "Media", "Health", "Retail", "Partners", "Systems", "Studio", "Group", "Analytics", "Co"]
COUNTRIES = ["United States", "United Kingdom", "Canada", "Germany", "Australia", "Netherlands", "India",
             "United Arab Emirates", "Singapore", "Ireland", "Sweden", "Spain"]
FEEDBACK = {"hired": ["Great communication and delivered on time.", "Smooth project, would hire again.",
                      "Clear scope, fast payment.", "Professional and responsive."],
            "closed_no_hire": ["We changed our plans and did not hire.", "Position filled internally."],
            "cancelled": ["Project cancelled by the client.", "Contract ended early, scope changed."]}


class ClientPool:
    def __init__(self, rng: random.Random, per_industry: int = 20, sketchy_rate: float = 0.12):
        self.clients, self.by_industry, self.sketchy = [], {}, []
        n = 0
        for ind in jobtext.INDUSTRIES:
            for _ in range(per_industry):
                n += 1
                sk = rng.random() < sketchy_rate
                c = {"client_id": f"cl-{n:04d}", "name": rng.choice(NAME_A) + rng.choice(NAME_B) + " " + rng.choice(NAME_C),
                     "industry": ind, "country": rng.choice(COUNTRIES), "_sketchy": sk}
                self.clients.append(c)
                (self.sketchy if sk else self.by_industry.setdefault(ind, [])).append(c)

    def pick(self, rng: random.Random, industry: str, scam: bool) -> str:
        if scam:
            return rng.choice(self.sketchy)["client_id"]
        pool = self.by_industry.get(industry) or [c for v in self.by_industry.values() for c in v]
        return rng.choice(pool)["client_id"]

    def finalize(self, rng: random.Random, history_jobs: list[dict]) -> list[dict]:
        by_client: dict[str, list[dict]] = {}
        for j in history_jobs:
            by_client.setdefault(j["client_id"], []).append(j)
        out = []
        for c in self.clients:
            hj = by_client.get(c["client_id"], [])
            hist, paid_total, hired = [], 0.0, 0
            for j in hj:
                if c["_sketchy"]:
                    oc = rng.choices(["hired", "closed_no_hire", "cancelled"], [25, 30, 45])[0]
                else:
                    oc = rng.choices(["hired", "closed_no_hire", "cancelled"], [78, 17, 5])[0]
                paid = round(j["final_price"], 2) if oc == "hired" else 0.0
                hired += oc == "hired"
                paid_total += paid
                hist.append({"job_id": j["job_id"], "title": j["title"], "outcome": oc, "paid": paid,
                             "feedback": rng.choice(FEEDBACK[oc])})
            posted = len(hj) + rng.randint(0, 4)
            sk = c["_sketchy"]
            out.append({
                "client_id": c["client_id"], "name": c["name"], "industry": c["industry"],
                "payment_verified": rng.random() < (0.15 if sk else 0.93),
                "total_spent": round(paid_total * (0.3 if sk else rng.uniform(1.0, 6.0)), 2),
                "hire_rate": round(hired / max(1, posted), 2),
                "avg_rating": round(rng.uniform(2.4, 4.0) if sk else rng.uniform(4.1, 5.0), 2) if hired or not sk else None,
                "jobs_posted": posted, "member_since": f"{rng.randint(2024, 2025) if sk else rng.randint(2014, 2023)}-{rng.randint(1, 12):02d}",
                "country": c["country"], "history": hist[:6]})
        return out


def _final_synth(rng, job):
    b = job["budget"]
    mid = (b["min"] + b["max"]) / 2
    return round(mid * rng.uniform(0.8, 1.0) * (rng.uniform(10, 120) if b["type"] == "hourly" else 1), 2)


def synth_history(ctxs: list, rng: random.Random, pool: ClientPool, n: int, id_prefix: str = "hist") -> list[dict]:
    out = []
    for i in range(n):
        ctx = rng.choice(ctxs)
        kind = "bid" if rng.random() < 0.55 else "off"
        posted = jobgen.CLOCK_START - timedelta(days=rng.uniform(60, 420))
        job, _ = jobgen.make_job(ctx, rng, job_id=f"{id_prefix}-s{i + 1:05d}", kind=kind, posted_at=posted,
                                 pick_client=pool.pick)
        job.update(kind="history", source="synthetic", final_price=_final_synth(rng, job))
        out.append(job)
    return out


def _parse_dt(s: str, rng, fallback_days=(60, 420)) -> datetime:
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        # real postings are from 2024; shift into the simulator's past so they sit before the clock start
        return jobgen.CLOCK_START - timedelta(days=(d.timestamp() % (86400 * 360)) / 86400 + 60)
    except ValueError:
        return jobgen.CLOCK_START - timedelta(days=rng.uniform(*fallback_days))


def real_history(rows: list[dict], rng: random.Random, pool: ClientPool, id_prefix: str = "hist") -> list[dict]:
    """History jobs from real titles/budgets/hourly rates. Descriptions are synthetic (not in the dump)."""
    inv = {c: k for k, c in CATEGORIES.items()}
    out = []
    for i, r in enumerate(rows):
        cat = r["category"]
        sids = [s for s in r["skills"] if s in SKILLS][:4]
        if not sids:
            cands = [s for s in SKILLS if SKILLS[s].category == cat and s not in jobgen.DISTRACTOR_SKILLS]
            sids = rng.sample(cands, min(len(cands), rng.randint(1, 3))) if cands else ["python"]
        reqs = [jobtext.requirement(s, rng.choice(["named", "implied"]), rng) for s in sids]
        industry = rng.choice(jobtext.INDUSTRIES)
        days = rng.randint(5, 60)
        if r["is_hourly"]:
            budget = {"type": "hourly", "min": int(r["hourly_low"]), "max": int(r["hourly_high"]), "currency": "USD"}
        else:
            b = r["budget"]
            budget = {"type": "fixed", "min": int(round(b * 0.9)), "max": int(round(b)), "currency": "USD"}
        job = {"job_id": f"{id_prefix}-r{i + 1:05d}", "client_id": pool.pick(rng, industry, False), "title": html.unescape(r["title"]),
               "description": jobtext.description(rng, industry, None, reqs, days), "category": CATEGORIES[cat],
               "required_skills": [SKILLS[s].name for s in sids], "budget": budget, "duration_days": days,
               "screening_questions": jobtext.screening(rng, sids), "posted_at": jobgen.iso(_parse_dt(r.get("published", ""), rng)),
               "connects_cost": max(4, min(16, 4 + int(budget["max"]) // (90 if budget["type"] == "hourly" else 700))),
               "kind": "history", "source": "kaggle_upwork_titles_budgets"}
        job["final_price"] = _final_synth(rng, job)
        out.append(job)
    del inv
    return out


def _pct(vals: list[float], q: float) -> float:
    s = sorted(vals)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo), 2)


def _stat(fixed: list[float], hourly: list[float]) -> dict:
    return {"n": len(fixed), "p10": _pct(fixed, .1), "p25": _pct(fixed, .25), "p50": _pct(fixed, .5),
            "p75": _pct(fixed, .75), "p90": _pct(fixed, .9), "hourly_p50": _pct(hourly, .5) if hourly else None}


def history_stats(history: list[dict]) -> dict:
    """Pricing stats per category and per skill (key 'skill:<Name>'); fixed jobs -> price percentiles."""
    groups: dict[str, tuple[list, list]] = {}

    def add(key, j):
        f, h = groups.setdefault(key, ([], []))
        if j["budget"]["type"] == "fixed":
            f.append(j["final_price"])
        else:
            h.append((j["budget"]["min"] + j["budget"]["max"]) / 2)

    for j in history:
        add(j["category"], j)
        add("All categories", j)
        for s in j["required_skills"]:
            add(f"skill:{s}", j)
    out = {}
    for k in sorted(groups):
        f, h = groups[k]
        if len(f) >= (1 if not k.startswith("skill:") else 8):
            out[k] = _stat(f, h)
    return out
