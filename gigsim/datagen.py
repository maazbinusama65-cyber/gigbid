"""Deterministic synthetic data generator (no LLM, no network).

    python -m gigsim.datagen --seed 1337 [--kaggle-dir DIR] [--no-kaggle] [--out-root .]

STAND-IN: the instructor's data/personas and gigsim seed data were not in the starter kit we
received; this generator reproduces the contract in docs/INTERFACES.md section 1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from . import docs_gen, jobgen, kaggle_import, market, proposals_gen
from .catalog_projects import PERSONA_IDS, PERSONAS, PROJECTS
from .catalog_skills import SKILLS

ROOT = Path(__file__).resolve().parent.parent
PROFILE_FIELDS = ["persona_id", "display_name", "headline", "skills", "hourly_rate_usd", "min_project_budget_usd",
                  "availability_hours_per_week", "weekly_connects_budget", "saved_searches"]
SEED_JOB_EXTRAS = ("kind", "source", "final_price", "persona_id")


def rng_for(seed: int, *label) -> random.Random:
    return random.Random(":".join(str(x) for x in (seed, *label)))


def dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, ensure_ascii=True) + "\n").encode("utf-8"))


def dump_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(json.dumps(r, ensure_ascii=True) + "\n" for r in rows).encode("utf-8"))


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def profile_for(pid: str, projects: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for p in projects:
        if p["kind"] == "core":
            for n in p["skills"]:
                counts[n] = counts.get(n, 0) + 1
    skills = [n for n, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))][:20]
    d = dict(PERSONAS[pid], persona_id=pid, skills=skills)
    return {k: d[k] for k in PROFILE_FIELDS} | {"primary_category": d["primary_category"]}


def write_persona(out: Path, pid: str, seed: int, projects: list[dict], prof: dict) -> None:
    root = out / "data" / "personas" / pid
    rng = rng_for(seed, "corpus", pid)
    public_prof = {k: prof[k] for k in PROFILE_FIELDS}
    dump(root / "profile.json", public_prof)
    for p in projects:
        prng = rng_for(seed, "project", pid, p["project_id"])
        modes = docs_gen._modes(p, prng)
        write_text(root / "case_studies" / f"{p['project_id']}.md", docs_gen.case_study(p, prng, modes) + "\n")
        docs_gen.write_repo(root, p, prng, modes)
    blocks = docs_gen.cv_blocks(pid, public_prof, projects, rng)
    write_text(root / "cv.md", docs_gen.cv_markdown(blocks))
    docs_gen.cv_pdf(blocks, root / "cv.pdf")
    dump(root / "reviews.json", docs_gen.reviews(pid, projects, rng))
    ctx = jobgen.build_ctx(pid, prof, projects)
    dump(root / "proposals.json", proposals_gen.generate(pid, ctx, rng_for(seed, "proposals", pid)))
    dump(root / "projects.json", [{"project_id": p["project_id"], "title": p["title"], "skills": p["skills"],
                                   "industry": p["industry"], "date": p["date"], "outcome_summary": p["outcome_summary"],
                                   "aliases": p["aliases"], "kind": p["kind"]} for p in projects])


def generate(seed: int = 1337, out_root: Path = ROOT, test_seed: int | None = None, use_kaggle: bool = True,
             n_dev: int = 200, n_test: int = 100, n_history: int = 1500, n_real: int = 1000) -> dict:
    out_root = Path(out_root)
    test_seed = test_seed if test_seed is not None else seed + 10007
    projects = {}
    profs = {}
    for pid in PERSONA_IDS:
        projects[pid] = []
        for p in PROJECTS[pid]:
            q = dict(p)
            q["skills"] = list(p["skills"])
            q["skills"] = [SKILLS[s].name if s in SKILLS else s for s in q["skills"]]
            projects[pid].append(q)
        profs[pid] = profile_for(pid, projects[pid])
        write_persona(out_root, pid, seed, projects[pid], profs[pid])
    ctxs = {pid: jobgen.build_ctx(pid, profs[pid], projects[pid]) for pid in PERSONA_IDS}

    seed_dir = out_root / "data" / "gigsim_seed"
    pool = market.ClientPool(rng_for(seed, "clients"))
    real_rows = kaggle_import.load_sample(seed_dir / "kaggle_sample.jsonl") if use_kaggle else []
    hrng = rng_for(seed, "history")
    n_real = min(n_real, len(real_rows), n_history)
    real = market.real_history(hrng.sample(real_rows, n_real), hrng, pool) if n_real else []
    synth = market.synth_history(list(ctxs.values()), hrng, pool, n_history - n_real)
    history = real + synth
    history.sort(key=lambda j: j["job_id"])

    dev_counts = jobgen.DEV_COUNTS if n_dev == 200 else _fit(jobgen.DEV_COUNTS, n_dev)
    test_counts = _fit(jobgen.DEV_COUNTS, n_test)
    stream, dev, dev_gold, test_gold = [], [], {}, {}
    for pid in PERSONA_IDS:
        c = ctxs[pid]
        stream += [j for j, _ in jobgen.make_set(c, rng_for(seed, "stream", pid), prefix=f"stream-{pid}", counts=jobgen.STREAM_COUNTS,
                                                 start=jobgen.CLOCK_START - jobgen_days(1), span_days=14, pick_client=pool.pick, forward=True)]
        items = jobgen.make_set(c, rng_for(seed, "dev", pid), prefix=f"dev-{pid}", counts=dev_counts,
                                start=jobgen.CLOCK_START, span_days=60, pick_client=pool.pick)
        dev += [dict(j, persona_id=pid) for j, _ in items]
        dev_gold[pid] = [g for _, g in items]
        titems = jobgen.make_set(c, rng_for(test_seed, "localtest", pid), prefix=f"test-{pid}", counts=test_counts,
                                 start=jobgen.CLOCK_START, span_days=60, pick_client=pool.pick)
        test_gold[pid] = [dict(g, job=j) for j, g in titems]
    for j in stream:
        j["kind"] = "stream"
    for j in dev:
        j["kind"] = "dev"
    clients = pool.finalize(rng_for(seed, "client-final"), history)
    stats = market.history_stats(history)

    dump_jsonl(seed_dir / "jobs.jsonl", history + stream + dev)
    dump_jsonl(seed_dir / "clients.jsonl", clients)
    dump(seed_dir / "history_stats.json", stats)
    dump(seed_dir / "generator_provenance.json", {
        "generator": "gigsim/datagen.py", "seed": seed, "local_test_seed": test_seed,
        "synthetic_stand_in": True,
        "history_jobs": {"total": len(history), "real_titles_budgets": len(real), "synthetic": len(synth)},
        "stream_jobs": len(stream), "dev_jobs": len(dev),
        "note": "Instructor gigsim/ and data/personas were not in the starter kit; everything here is synthetic "
                "except titles/budgets/hourly rates of history jobs counted under real_titles_budgets."})
    for pid in PERSONA_IDS:
        dump_jsonl(out_root / "evals" / "datasets" / f"dev_{pid}.jsonl", dev_gold[pid])
        dump_jsonl(out_root / "data" / "processed" / f"local_test_{pid}.jsonl", test_gold[pid])
    return {"history": len(history), "real_history": len(real), "stream": len(stream), "dev": len(dev),
            "clients": len(clients), "hash": tree_hash(out_root)}


def jobgen_days(n):
    from datetime import timedelta
    return timedelta(days=n)


def _fit(counts: dict, n: int) -> dict:
    tot = sum(counts.values())
    out = {k: max(1, round(v * n / tot)) for k, v in counts.items()}
    out["bid"] += n - sum(out.values())
    return out


def tree_hash(out_root: Path) -> str:
    """sha256 over every generated artefact (not the optional kaggle sample / provenance of the import)."""
    out_root = Path(out_root)
    h = hashlib.sha256()
    files = []
    for base in ("data/personas", "data/gigsim_seed", "evals/datasets"):
        files += [p for p in (out_root / base).rglob("*") if p.is_file() and p.name != "kaggle_provenance.json"]
    files += sorted((out_root / "data" / "processed").glob("local_test_*.jsonl"))
    for p in sorted(files, key=lambda p: p.relative_to(out_root).as_posix()):
        h.update(p.relative_to(out_root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic GigBid stand-in data generator")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--test-seed", type=int, default=None)
    ap.add_argument("--out-root", type=Path, default=ROOT)
    ap.add_argument("--kaggle-dir", type=Path, default=None, help="folder of real job CSVs to (re)build the sample from")
    ap.add_argument("--no-kaggle", action="store_true", help="ignore data/gigsim_seed/kaggle_sample.jsonl")
    a = ap.parse_args(argv)
    if a.kaggle_dir:
        kaggle_import.write_sample(a.kaggle_dir, a.out_root / "data" / "gigsim_seed" / "kaggle_sample.jsonl", seed=a.seed)
    res = generate(a.seed, a.out_root, a.test_seed, use_kaggle=not a.no_kaggle)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
