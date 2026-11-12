"""Embedders: the real open model (lazy, cached) and an offline hash-based fake for tests.

The real model (BAAI/bge-small-en-v1.5 on CPU) is only loaded on first ``encode`` and is
process-cached. A deterministic hash embedder is used by unit tests (offline); real evals must
not silently fall back to it (``allow_fallback`` defaults to False).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import zlib
from typing import Protocol

import numpy as np

from rag import config

log = logging.getLogger(__name__)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str], *, is_query: bool = False) -> np.ndarray: ...


class HashEmbedder:
    """Signed feature-hashing bag of uni+bigrams, L2-normalised. Deterministic, no model needed."""

    def __init__(self, dim: int = 384):
        self.dim = dim
        self.name = f"hash-{dim}"

    def encode(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            toks = re.findall(r"[a-z0-9+#]+", text.lower())
            feats = toks + [a + "_" + b for a, b in zip(toks, toks[1:], strict=False)]
            for f in feats:
                h = zlib.crc32(f.encode("utf-8"))
                out[i, h % self.dim] += 1.0 if (h >> 16) & 1 else -1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


class SentenceTransformerEmbedder:
    """Lazy wrapper around sentence-transformers with an in-memory query cache."""

    def __init__(self, model_name: str, *, max_seq_length: int = 384, batch_size: int = 32):
        self.name = model_name
        self._max_seq = max_seq_length
        self._batch = batch_size
        self._model = None
        self._lock = threading.Lock()
        self._qcache: dict[str, np.ndarray] = {}

    def _load(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    model = SentenceTransformer(self.name, device="cpu")
                    model.max_seq_length = self._max_seq
                    self._model = model
        return self._model

    def encode(self, texts: list[str], *, is_query: bool = False) -> np.ndarray:
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        if is_query:
            missing = [t for t in dict.fromkeys(texts) if t not in self._qcache]
            if missing:
                vecs = self._encode_raw([BGE_QUERY_PREFIX + t for t in missing])
                self._qcache.update(zip(missing, vecs, strict=True))
            return np.stack([self._qcache[t] for t in texts])
        return self._encode_raw(texts)

    def _encode_raw(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(texts, batch_size=self._batch, normalize_embeddings=True,
                            show_progress_bar=False, convert_to_numpy=True)
        return vecs.astype(np.float32)


_EMBEDDERS: dict[str, Embedder] = {}


def get_embedder(name: str | None = None, *, allow_fallback: bool = False) -> Embedder:
    """Return the process-wide embedder. Env RAG_EMBEDDER=hash forces the offline fake."""
    forced = os.environ.get("RAG_EMBEDDER", "").strip().lower()
    if forced in ("hash", "fake"):
        if "hash" not in _EMBEDDERS:
            _EMBEDDERS["hash"] = HashEmbedder()
        return _EMBEDDERS["hash"]
    name = name or config.embedding_model()
    if name not in _EMBEDDERS:
        emb = SentenceTransformerEmbedder(name)
        if allow_fallback:
            try:
                emb._load()
            except Exception as exc:  # noqa: BLE001 - offline fallback is explicit opt-in
                log.warning("embedding model %s unavailable (%s); using hash embedder", name, exc)
                _EMBEDDERS[name] = HashEmbedder()
                return _EMBEDDERS[name]
        _EMBEDDERS[name] = emb
    return _EMBEDDERS[name]
