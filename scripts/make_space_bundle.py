"""Assemble the folder a Hugging Face Space (Docker SDK) needs.

    python scripts/make_space_bundle.py            # writes ./space_bundle/

The Space is its own git repository whose root must hold a Dockerfile and a README.md with YAML front matter, so the
bundle copies only what the container needs (code, personas, simulator seed, web sources) next to the deploy files.
`constraints.txt` pins the dependency versions that were verified in a clean environment.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "space_bundle"
DEPLOY = ROOT / "deploy" / "space"
SKIP_DIRS = {"__pycache__", "node_modules", "dist", "tests", "test-results", "playwright-report", ".pytest_cache",
             "gigbid.egg-info", "processed", ".venv"}
SKIP_SUFFIXES = {".pyc", ".sqlite", ".db"}
SKIP_FILES = {"kaggle_sample.jsonl"}      # derived from a third-party dataset; never redistributed in the bundle
COPY_TREES = ["agent", "rag", "mcp_servers", "gigsim", "apps/api", "apps/web", "data/personas", "data/gigsim_seed",
              "data/policy_pack"]
COPY_FILES = ["pyproject.toml"]


def ignore(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n in SKIP_DIRS or n in SKIP_FILES or Path(n).suffix in SKIP_SUFFIXES]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for tree in COPY_TREES:
        src = ROOT / tree
        if not src.exists():
            raise SystemExit(f"missing {tree}")
        shutil.copytree(src, OUT / tree, ignore=ignore)
    for f in COPY_FILES:
        (OUT / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / f, OUT / f)
    for name in ("Dockerfile", "README.md", "start.py", "constraints.txt"):
        src = DEPLOY / name
        if not src.exists():
            raise SystemExit(f"missing deploy/space/{name}")
        shutil.copy2(src, OUT / name)
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file()) / 1e6
    print(f"bundle written to {OUT} ({size:.1f} MB, {sum(1 for _ in OUT.rglob('*') if _.is_file())} files)")


if __name__ == "__main__":
    main()
