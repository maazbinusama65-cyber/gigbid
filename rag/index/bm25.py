"""Dependency-free BM25 (Okapi) over pre-tokenised documents."""
from __future__ import annotations

import math
from collections import Counter

import numpy as np

from rag.text import tokenize


class BM25Index:
    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.n = len(texts)
        self._tf: list[Counter] = []
        self._postings: dict[str, list[int]] = {}
        lengths = []
        for i, text in enumerate(texts):
            toks = tokenize(text)
            tf = Counter(toks)
            self._tf.append(tf)
            lengths.append(len(toks))
            for term in tf:
                self._postings.setdefault(term, []).append(i)
        self._len = np.array(lengths, dtype=np.float32)
        self._avgdl = float(self._len.mean()) if self.n else 0.0
        self._idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5))
                     for t, p in self._postings.items()}

    def scores(self, query: str) -> np.ndarray:
        out = np.zeros(self.n, dtype=np.float32)
        if not self.n:
            return out
        # query-term frequency is ignored on purpose: long job posts would otherwise let one
        # repeated word dominate.
        for term in set(tokenize(query)):
            plist = self._postings.get(term)
            if not plist:
                continue
            idf = self._idf[term]
            for i in plist:
                tf = self._tf[i][term]
                norm = 1 - self.b + self.b * self._len[i] / (self._avgdl or 1.0)
                out[i] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return out
