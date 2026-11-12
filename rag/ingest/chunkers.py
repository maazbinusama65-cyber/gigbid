"""Chunkers. `fixed_chunks` is the V0 baseline; `structure_chunks` is used by every other variant.

Structure-aware means: markdown is split on headings (heading chain kept in the chunk), code is
split on top-level definitions (file path kept), and reviews/proposals stay whole (one voice per
chunk). Chunks are plain dicts ``{"text": str, "heading": str}``.
"""
from __future__ import annotations

import re

from rag.types import Document

FIXED_WORDS = 90
FIXED_OVERLAP = 20
MAX_WORDS = 170
MIN_WORDS = 25

_WORD_RE = re.compile(r"\S+\s*")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_CODE_BOUNDARY_RE = re.compile(
    r"^(?:def |class |async def |function |export |const \w+\s*=|interface |type \w+\s*=|"
    r"CREATE |WITH |SELECT |INSERT |@\w+)", re.MULTILINE)


def fixed_chunks(text: str, size: int = FIXED_WORDS, overlap: int = FIXED_OVERLAP) -> list[dict]:
    """Sliding word window, blind to structure (V0)."""
    if size <= overlap:
        raise ValueError("size must exceed overlap")
    words = _WORD_RE.findall(text)
    if not words:
        return []
    chunks, step = [], size - overlap
    for start in range(0, len(words), step):
        piece = "".join(words[start:start + size]).strip()
        if piece:
            chunks.append({"text": piece, "heading": ""})
        if start + size >= len(words):
            break
    return chunks


def _split_long(text: str, max_words: int) -> list[str]:
    """Pack paragraphs (then sentences) into pieces of at most max_words."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    pieces: list[str] = []
    buf: list[str] = []
    count = 0
    for para in paras:
        n = len(para.split())
        if n > max_words:  # a single huge paragraph: fall back to a fixed window
            if buf:
                pieces.append("\n\n".join(buf))
                buf, count = [], 0
            pieces.extend(c["text"] for c in fixed_chunks(para, max_words, max_words // 5))
            continue
        if count + n > max_words and buf:
            pieces.append("\n\n".join(buf))
            buf, count = [], 0
        buf.append(para)
        count += n
    if buf:
        pieces.append("\n\n".join(buf))
    return pieces


def markdown_chunks(text: str, doc_title: str = "", max_words: int = MAX_WORDS,
                    min_words: int = MIN_WORDS) -> list[dict]:
    sections: list[tuple[str, list[str]]] = []
    chain: list[tuple[int, str]] = []
    cur_head, cur_lines = doc_title, []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        m = None if in_fence else _HEADING_RE.match(line)
        if m:
            sections.append((cur_head, cur_lines))
            level = len(m.group(1))
            chain = [c for c in chain if c[0] < level] + [(level, m.group(2).strip())]
            cur_head = " > ".join(c[1] for c in chain)
            cur_lines = []
        else:
            cur_lines.append(line)
    sections.append((cur_head, cur_lines))

    chunks: list[dict] = []
    carry, carry_head = "", doc_title
    for head, lines in sections:
        body = "\n".join(lines).strip()
        if not body and not carry:
            continue
        if carry:
            body = (carry + "\n\n" + body).strip()
            carry = ""
        if len(body.split()) < min_words:
            carry, carry_head = body, head  # tiny section: merge into the next one
            continue
        for piece in _split_long(body, max_words):
            chunks.append({"text": f"{head}\n{piece}".strip() if head else piece,
                           "heading": head})
    if carry:
        if chunks and len(carry.split()) < min_words:
            chunks[-1]["text"] += "\n\n" + carry
        else:
            chunks.append({"text": f"{carry_head}\n{carry}".strip(), "heading": carry_head})
    return chunks


def code_chunks(text: str, path: str = "", max_words: int = MAX_WORDS) -> list[dict]:
    """Split on top-level definitions; pack neighbouring small definitions together."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if _CODE_BOUNDARY_RE.match(ln)]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    blocks = []
    for a, b in zip(starts, starts[1:] + [len(lines)], strict=True):
        block = "\n".join(lines[a:b]).strip("\n")
        if block.strip():
            blocks.append(block)
    header = f"# file: {path}\n" if path else ""
    chunks, buf, count = [], [], 0
    for block in blocks:
        n = len(block.split())
        if buf and count + n > max_words:
            chunks.append("\n".join(buf))
            buf, count = [], 0
        if n > max_words * 2:  # giant function: window it
            if buf:
                chunks.append("\n".join(buf))
                buf, count = [], 0
            chunks.extend(c["text"] for c in fixed_chunks(block, max_words, 15))
            continue
        buf.append(block)
        count += n
    if buf:
        chunks.append("\n".join(buf))
    return [{"text": header + c, "heading": path} for c in chunks]


def structure_chunks(doc: Document) -> list[dict]:
    if doc.type in ("case_study", "readme", "cv"):
        return markdown_chunks(doc.text, doc.title)
    if doc.type == "code":
        return code_chunks(doc.text, doc.source)
    if len(doc.text.split()) <= 2 * MAX_WORDS:  # review / proposal / summary stay whole
        return [{"text": doc.text.strip(), "heading": doc.title}] if doc.text.strip() else []
    return [{"text": p, "heading": doc.title} for p in _split_long(doc.text, MAX_WORDS)]


def chunk_document(doc: Document, kind: str) -> list[dict]:
    """kind = 'fixed' (V0) or 'struct' (everything else)."""
    if kind == "fixed":
        return fixed_chunks(doc.text)
    if kind == "struct":
        return structure_chunks(doc)
    raise ValueError(f"unknown chunk kind {kind!r}")
