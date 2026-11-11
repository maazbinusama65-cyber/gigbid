"""Config loading. Everything tunable lives in agent/config.yaml (+ env overrides)."""
from __future__ import annotations

import copy
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "agent" / "config.yaml"


def _deep_get(d: dict, path: str, default=None):
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


class Config(dict):
    def get_path(self, path: str, default=None):
        return _deep_get(self, path, default)

    @property
    def profile(self) -> str:
        return os.getenv("MODEL_PROFILE") or self["models"]["profile"]

    @property
    def marketplace_mode(self) -> str:
        return os.getenv("MARKETPLACE_MODE") or self["marketplace"]["mode"]

    @property
    def rag_variant(self) -> str:
        return os.getenv("RAG_VARIANT") or self["rag"]["variant"]


@lru_cache(maxsize=1)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(path: str | Path | None = None, overrides: dict | None = None) -> Config:
    """Return a fresh deep copy so callers can mutate safely (tests, ablations)."""
    base = copy.deepcopy(_load(str(path or CONFIG_PATH)))
    cfg = Config(base)
    for dotted, value in (overrides or {}).items():
        cur = cfg
        parts = dotted.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
    return cfg
