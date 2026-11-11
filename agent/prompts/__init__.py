"""Versioned prompt loader: one .md per node, no inline prompts anywhere else (CI-enforced)."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@lru_cache(maxsize=None)
def load_prompt(name: str) -> tuple[str, str]:
    """Return (version, body). First line of each file: `<!-- version: N -->`."""
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = re.match(r"<!--\s*version:\s*([\w.]+)\s*-->\s*", raw)
    return (m.group(1) if m else "0", raw[m.end():] if m else raw)
