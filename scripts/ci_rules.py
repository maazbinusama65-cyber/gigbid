"""Repo rules the CI must enforce (assignment 'Rules your CI must enforce'):

  1. no secrets in the repo           2. nothing under gigsim/ changed vs. its manifest
  3. every prompt lives in agent/prompts/ (no inline prompts)
  4. every number in README.md traces to a file in evals/results/ (marker comments)

    python scripts/ci_rules.py            # check
    python scripts/ci_rules.py --update-gigsim-manifest
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECRET_PATTERNS = [
    r"gsk_[A-Za-z0-9]{20,}", r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{30,}", r"gho_[A-Za-z0-9]{30,}",
    r"AKIA[0-9A-Z]{16}", r"xox[bp]-[A-Za-z0-9-]{10,}", r"-----BEGIN (RSA |EC )?PRIVATE KEY-----",
    r"AIza[0-9A-Za-z_\-]{30,}",
]
MANIFEST = ROOT / "gigsim" / ".manifest.sha256"


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / p for p in out.splitlines() if (ROOT / p).is_file()]


def check_secrets() -> list[str]:
    bad = []
    for f in tracked_files():
        if f.suffix in {".png", ".jpg", ".pdf", ".zip", ".npy", ".sqlite", ".woff2", ".ico"} or f.name == "package-lock.json":
            continue
        if f.name == ".env":
            bad.append(f"{f} is tracked")
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for p in SECRET_PATTERNS:
            if re.search(p, txt) and f.name != "ci_rules.py":
                bad.append(f"{f.relative_to(ROOT)}: matches {p}")
    return bad


def _gigsim_hashes() -> dict[str, str]:
    base = ROOT / "gigsim"
    return {str(p.relative_to(base)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(base.rglob("*")) if p.is_file() and p.name != ".manifest.sha256" and "__pycache__" not in p.parts}


def check_gigsim() -> list[str]:
    if not MANIFEST.exists():
        return ["gigsim/.manifest.sha256 missing (run --update-gigsim-manifest once when importing the provided gigsim)"]
    want = json.loads(MANIFEST.read_text())
    have = _gigsim_hashes()
    return [f"gigsim/{k} changed" for k in have if want.get(k) != have[k]] + [f"gigsim/{k} removed" for k in want if k not in have]


def check_prompts() -> list[str]:
    bad = []
    for f in (ROOT / "agent").rglob("*.py"):
        txt = f.read_text(encoding="utf-8")
        for m in re.finditer(r'"""(.*?)"""', txt, re.S):
            body = m.group(1)
            if re.search(r"\byou are (the|a|an) [A-Za-z ]+(agent|writer|critic|analyst|assessor|guard|strategist|scout|liaison|matcher|judge)", body, re.I):
                bad.append(f"{f.relative_to(ROOT)}: looks like an inline prompt")
    return bad


def check_readme_numbers() -> list[str]:
    """Numbers in README tables are wrapped as `<!--r:file.json:key-->` and must exist in evals/results."""
    bad = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for fname, key in re.findall(r"<!--r:([\w./-]+):([\w.\[\]-]+)-->", readme):
        p = ROOT / "evals" / "results" / fname
        if not p.exists():
            bad.append(f"README cites missing results file {fname}")
            continue
        if p.suffix == ".json" and key not in p.read_text(encoding="utf-8"):
            bad.append(f"README cites {fname}:{key} which is not in the file")
    return bad


def main() -> int:
    if "--update-gigsim-manifest" in sys.argv:
        MANIFEST.write_text(json.dumps(_gigsim_hashes(), indent=1))
        print("manifest written")
        return 0
    problems = {"secrets": check_secrets(), "gigsim": check_gigsim(), "prompts": check_prompts(),
                "readme": check_readme_numbers()}
    rc = 0
    for name, items in problems.items():
        print(f"[{'FAIL' if items else 'ok'}] {name}")
        for i in items:
            print("   -", i)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
