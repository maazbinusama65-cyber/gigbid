"""RAG settings: values come from agent/config.yaml (`rag`, `models`) with env overrides."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "agent" / "config.yaml"


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _p(env: str, default: Path) -> Path:
    val = os.environ.get(env)
    return Path(val) if val else default


def personas_root() -> Path:
    return _p("RAG_PERSONAS_DIR", REPO_ROOT / "data" / "personas")


def index_root() -> Path:
    return _p("RAG_INDEX_DIR", REPO_ROOT / "data" / "processed" / "index")


def default_variant() -> str:
    """Config `rag.variant`, overridden by env RAG_VARIANT."""
    return os.environ.get("RAG_VARIANT") or load_config().get("rag", {}).get("variant", "v0_naive")


def default_k() -> int:
    return int(load_config().get("rag", {}).get("k", 5))


def embedding_model() -> str:
    return load_config().get("models", {}).get("embeddings", "BAAI/bge-small-en-v1.5")


def reranker_model() -> str:
    return load_config().get("models", {}).get("reranker", "cross-encoder/ms-marco-MiniLM-L-6-v2")


def default_portfolio_id() -> str | None:
    return os.environ.get("PORTFOLIO_ID")
