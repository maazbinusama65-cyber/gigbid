"""Cross-encoder reranker (lazy, cached) and an offline lexical stand-in for tests."""
from __future__ import annotations

import logging
import os
import threading
from typing import Protocol

from rag import config
from rag.text import content_words

log = logging.getLogger(__name__)


class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class LexicalReranker:
    """Offline stand-in: fraction of query content words present in the passage."""

    name = "lexical-overlap"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = set(content_words(query))
        if not q:
            return [0.0] * len(passages)
        return [len(q & set(content_words(p))) / len(q) for p in passages]


class CrossEncoderReranker:
    def __init__(self, model_name: str, *, max_length: int = 256, batch_size: int = 32):
        self.name = model_name
        self._max_length = max_length
        self._batch = batch_size
        self._model = None
        self._lock = threading.Lock()
        self._cache: dict[tuple[str, str], float] = {}

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self.name, device="cpu",
                                               max_length=self._max_length)
        return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        todo = [(query, p) for p in dict.fromkeys(passages) if (query, p) not in self._cache]
        if todo:
            preds = self._load().predict(todo, batch_size=self._batch, show_progress_bar=False)
            for pair, val in zip(todo, preds, strict=True):
                self._cache[pair] = float(val)
        return [self._cache[(query, p)] for p in passages]


_RERANKERS: dict[str, Reranker] = {}


def get_reranker(name: str | None = None, *, allow_fallback: bool = False) -> Reranker:
    if os.environ.get("RAG_EMBEDDER", "").strip().lower() in ("hash", "fake"):
        return _RERANKERS.setdefault("lexical", LexicalReranker())
    name = name or config.reranker_model()
    if name not in _RERANKERS:
        rr = CrossEncoderReranker(name)
        if allow_fallback:
            try:
                rr._load()
            except Exception as exc:  # noqa: BLE001
                log.warning("reranker %s unavailable (%s); using lexical", name, exc)
                _RERANKERS[name] = LexicalReranker()
                return _RERANKERS[name]
        _RERANKERS[name] = rr
    return _RERANKERS[name]
