"""Tiny config helpers shared by servers (reads agent/config.yaml without importing ``agent``)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "agent" / "config.yaml"


def load_yaml_config(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path or os.getenv("GIGBID_CONFIG") or CONFIG_PATH)
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def marketplace_mode(cfg: dict[str, Any]) -> str:
    return os.getenv("MARKETPLACE_MODE") or cfg.get("marketplace", {}).get("mode", "gigsim")
