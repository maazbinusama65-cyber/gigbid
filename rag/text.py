"""Small text utilities shared by ingestion, BM25, retrieval and verification."""
from __future__ import annotations

import re

STOPWORDS = frozenset(
    """a an and are as at be been but by can could do does for from had has have he her his i if in
    into is it its me my of on or our she so than that the their them then there these they this
    those to up us was we were what when where which who will with you your about also any all
    both each few more most other some such only own same too very just should would may might
    must need needs looking want wants like get got per via using use used""".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-_]*", re.IGNORECASE)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n+")


def _norm_token(tok: str) -> str:
    tok = tok.lower().rstrip(".-_")
    return tok


def tokenize(text: str, *, drop_stop: bool = True) -> list[str]:
    """Lowercase tokens; compound tokens (snake_case, dotted, hyphenated) also emit their parts.

    Keeps technical tokens such as ``c++``, ``node.js`` and ``scikit-learn`` intact so exact tool
    names stay matchable by BM25.
    """
    out: list[str] = []
    for raw in _TOKEN_RE.findall(text):
        tok = _norm_token(raw)
        if not tok:
            continue
        parts = re.split(r"[._\-]", tok)
        if len(parts) > 1:
            out.append(tok)
            out.extend(p for p in parts if p)
        else:
            out.append(tok)
    if drop_stop:
        out = [t for t in out if t not in STOPWORDS]
    return out


def content_words(text: str) -> list[str]:
    """Stemmed-ish content words (for claim/evidence overlap)."""
    words = []
    for tok in tokenize(text):
        if len(tok) < 3 and not tok.isdigit():
            continue
        words.append(stem(tok))
    return words


def stem(tok: str) -> str:
    """Very light suffix stripping, good enough for overlap checks."""
    for suf in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            base = tok[: -len(suf)]
            return base + "y" if suf == "ies" else base
    return tok


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENT_SPLIT_RE.split(text) if p and p.strip()]
    return parts


def word_count(text: str) -> int:
    return len(text.split())
