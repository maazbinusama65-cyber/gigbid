"""Generic importer for real marketplace job dumps (e.g. the Kaggle 'Upwork jobs' CSVs).

The files are UNTRUSTED DATA: they are only parsed with the stdlib csv module (never executed), text
is length-capped and screened for URLs / contact details / instruction-like strings, and nothing is
used verbatim except title, budget, hourly range, country and date.

Columns are sniffed generically (title, description, skills, budget, hourly_low/high, category,
country, date). The dataset we received only has title/budget/hourly/country/date, so descriptions
and required skills are NOT real: skills are keyword-matched from titles and descriptions are synthetic.

    python -m gigsim.kaggle_import --kaggle-dir data/external/upwork_all_jobs_200k
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from .catalog_skills import SKILLS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "gigsim_seed" / "kaggle_sample.jsonl"

COLS = {
    "title": ["title", "job_title", "name", "headline"],
    "description": ["description", "desc", "summary", "details", "text", "job_description"],
    "skills": ["skills", "tags", "required_skills", "skill_tags"],
    "budget": ["budget", "amount", "price", "fixed_price", "fixed_budget"],
    "hourly_low": ["hourly_low", "hourly_min", "min_rate", "rate_min", "hourly_rate_min"],
    "hourly_high": ["hourly_high", "hourly_max", "max_rate", "rate_max", "hourly_rate_max"],
    "is_hourly": ["is_hourly", "hourly", "job_type", "type"],
    "category": ["category", "subcategory", "category_name", "job_category"],
    "country": ["country", "client_country", "location"],
    "published": ["published_date", "posted_at", "date", "published", "created_at", "posted"],
}

CATEGORY_KW = [  # first match wins
    ("writing", r"writer|copywrit|translat|blog|article|proofread|ghostwrit|editor|content writ|script ?writ"),
    ("ai_ml", r"machine learning|\bml\b|\bai\b|\bllm\b|gpt|chatbot|deep learning|computer vision|\bnlp\b|openai|langchain|tensorflow|pytorch|neural"),
    ("data_eng", r"\betl\b|data engineer|data pipeline|airflow|snowflake|bigquery|\bdbt\b|data warehouse|web scrap|scraper|scraping"),
    ("analytics", r"data analy|power ?bi|tableau|dashboard|excel|\bsql\b|looker|google sheets|spreadsheet|data visuali|\bkpi\b|statistic|a/b test"),
    ("devops", r"devops|\baws\b|kubernetes|docker|terraform|ci/cd|azure|gcp|cloud engineer|sysadmin"),
    ("mobile", r"android|\bios\b|flutter|react native|mobile app|swift|kotlin|iphone"),
    ("web", r"web ?dev|front ?end|back ?end|full ?stack|react|next\.?js|node\.?js|django|laravel|\bphp\b|wordpress|shopify|\bapi\b|website|javascript|typescript|vue|angular|python dev|software engineer|developer"),
    ("design", r"logo|figma|ui/ux|\bux\b|graphic|illustrat|brand|video edit|animation|photoshop|3d model"),
    ("marketing", r"\bseo\b|marketing|\bads\b|social media|lead gen|email campaign|sales|bookkeep|virtual assistant"),
]
SKILL_KW = [  # ordered; first group longer phrases
    (r"react native", "react_native"), (r"next\.?js", "nextjs"), (r"node\.?js|\bnode\b", "nodejs"),
    (r"\breact\b", "react"), (r"typescript", "typescript"), (r"power ?bi", "powerbi"), (r"tableau", "tableau"),
    (r"looker", "looker_studio"), (r"google sheets|apps script", "google_sheets"), (r"\bexcel\b", "excel"),
    (r"\bsql\b|mysql|postgres", "sql"), (r"bigquery", "bigquery"), (r"snowflake", "snowflake"), (r"\bdbt\b", "dbt"),
    (r"airflow", "airflow"), (r"\betl\b", "etl"), (r"scrap", "web_scraping"), (r"\bpython\b", "python"),
    (r"pandas", "pandas"), (r"scikit|sklearn", "sklearn"), (r"pytorch", "pytorch"), (r"hugging ?face", "huggingface"),
    (r"langchain", "langchain"), (r"openai|gpt|chatgpt", "openai_api"), (r"\brag\b", "rag"), (r"\bnlp\b", "nlp"),
    (r"computer vision|opencv|yolo", "computer_vision"), (r"fine.?tun", "finetuning"), (r"prompt", "prompt_eng"),
    (r"forecast", "forecasting"), (r"a/b test", "ab_testing"), (r"stripe", "stripe"), (r"graphql", "graphql"),
    (r"django", "django"), (r"fastapi", "fastapi"), (r"docker", "docker"), (r"\baws\b", "aws"), (r"redis", "redis"),
    (r"mongo", "mongodb"), (r"supabase", "supabase"), (r"tailwind", "tailwind"), (r"elasticsearch", "elasticsearch"),
    (r"swift|\bios\b|iphone", "swift"), (r"kotlin|android", "kotlin"), (r"flutter", "flutter"), (r"unity", "unity"),
    (r"figma", "figma"), (r"logo", "logo_design"), (r"illustrator", "illustrator"), (r"video edit", "video_editing"),
    (r"\bseo\b", "seo_writing"), (r"copywrit", "copywriting"), (r"translat", "translation"), (r"ghostwrit", "ghostwriting"),
    (r"google ads|ppc", "google_ads"), (r"email (marketing|campaign)", "email_marketing"), (r"social media", "social_media"),
    (r"lead gen", "lead_gen"), (r"kubernetes", "kubernetes"), (r"terraform", "terraform"), (r"spring boot|\bjava\b", "java_spring"),
    (r"\.net|c#", "dotnet"), (r"laravel|\bphp\b", "php_laravel"), (r"\brails\b|ruby", "ruby_rails"), (r"\bgolang\b|\bgo dev", "golang_services"),
    (r"shopify", "shopify_theme"), (r"wordpress", "wordpress_plugin"), (r"salesforce", "salesforce"), (r"bookkeep", "bookkeeping"),
    (r"pentest|penetration", "pentesting"), (r"solidity|smart contract", "solidity"), (r"voice.?over", "voiceover"),
]
_SKILL_RX = [(re.compile(p, re.I), s) for p, s in SKILL_KW if s in SKILLS]
_CAT_RX = [(c, re.compile(p, re.I)) for c, p in CATEGORY_KW]
_UNSAFE = re.compile(r"https?://|www\.|@\w|\+?\d[\d\s().-]{8,}|ignore (all )?(previous|prior)|system prompt|"
                     r"whatsapp|telegram|skype|\bdm me\b|password|api[_ ]?key", re.I)


def pick(row: dict, key: str):
    for c in COLS[key]:
        if c in row and row[c] not in (None, ""):
            return row[c]
    return None


def _num(v):
    try:
        x = float(str(v).replace(",", "").replace("$", "").strip())
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def classify(text: str) -> str | None:
    for cat, rx in _CAT_RX:
        if rx.search(text):
            return cat
    return None


def extract_skills(text: str) -> list[str]:
    out: list[str] = []
    for rx, sid in _SKILL_RX:
        if rx.search(text) and sid not in out:
            out.append(sid)
    return out[:5]


def normalize(row: dict) -> dict | None:
    title = re.sub(r"\s+", " ", html.unescape(str(pick(row, "title") or ""))).strip()
    if not (12 <= len(title) <= 110) or _UNSAFE.search(title):
        return None
    if sum(ch.isascii() for ch in title) < 0.95 * len(title) or title.isupper():
        return None
    desc = str(pick(row, "description") or "")[:600]
    if _UNSAFE.search(desc):
        desc = ""
    hourly_raw = str(pick(row, "is_hourly") or "").strip().lower()
    lo, hi = _num(pick(row, "hourly_low")), _num(pick(row, "hourly_high"))
    budget = _num(pick(row, "budget"))
    is_hourly = hourly_raw in ("true", "1", "yes", "hourly") or (lo is not None and budget is None)
    rec = {"title": title, "description": desc, "is_hourly": bool(is_hourly), "country": str(pick(row, "country") or "")[:40],
           "published": str(pick(row, "published") or "")[:25]}
    if is_hourly:
        if not lo or not hi or not (3 <= lo <= hi <= 400):
            return None
        rec.update(hourly_low=lo, hourly_high=hi)
    else:
        if budget is None or not (25 <= budget <= 25000):
            return None
        rec["budget"] = round(budget, 2)
    declared = pick(row, "skills")
    text = f"{title} {declared or ''} {desc}"
    rec["category"] = classify(text)
    rec["skills"] = extract_skills(text)
    return rec if rec["category"] else None


def _open_csvs(folder: Path):
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() == ".csv":
            yield p.name, open(p, newline="", encoding="utf-8", errors="replace")
        elif p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as z:
                for n in sorted(z.namelist()):
                    if n.lower().endswith(".csv"):
                        yield f"{p.name}:{n}", io.TextIOWrapper(z.open(n), encoding="utf-8", errors="replace", newline="")


def iter_records(folder: Path):
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    for _name, fh in _open_csvs(folder):
        with fh:
            for row in csv.DictReader(fh):
                rec = normalize(row)
                if rec:
                    yield rec


def build_sample(folder: Path, per_category: int = 450, seed: int = 1337) -> tuple[list[dict], dict]:
    """Deterministic hash-ranked sample, <= per_category rows per category, de-duplicated by title."""
    best: dict[str, dict[str, tuple[str, dict]]] = {}
    total = kept = 0
    for rec in iter_records(folder):
        total += 1
        key = hashlib.sha1(f"{seed}:{rec['title'].lower()}".encode()).hexdigest()
        bucket = best.setdefault(rec["category"], {})
        t = rec["title"].lower()
        if t in bucket:
            continue
        bucket[t] = (key, rec)
        if len(bucket) > per_category * 3:  # bound memory: keep smallest keys
            for k, _ in sorted(bucket.items(), key=lambda kv: kv[1][0])[per_category:]:
                bucket.pop(k)
    rows = []
    for cat in sorted(best):
        top = sorted(best[cat].values(), key=lambda kv: kv[0])[:per_category]
        rows += [r for _, r in top]
    kept = len(rows)
    meta = {"source": str(folder.name), "usable_rows_scanned": total, "sampled_rows": kept,
            "per_category": {c: sum(1 for r in rows if r["category"] == c) for c in sorted(best)}}
    return rows, meta


def write_sample(folder: Path, out: Path = DEFAULT_OUT, per_category: int = 450, seed: int = 1337) -> dict:
    rows, meta = build_sample(folder, per_category, seed)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    meta["out"] = str(out)
    (out.parent / "kaggle_provenance.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
    return meta


def load_sample(path: Path = DEFAULT_OUT) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--kaggle-dir", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--per-category", type=int, default=450)
    ap.add_argument("--seed", type=int, default=1337)
    a = ap.parse_args(argv)
    print(json.dumps(write_sample(a.kaggle_dir, a.out, a.per_category, a.seed), indent=2))


if __name__ == "__main__":
    main()
