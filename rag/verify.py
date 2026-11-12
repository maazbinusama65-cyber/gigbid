"""B3 claim verification: split a draft into atomic claims, ground each against the retrieved
evidence, and remove/rewrite unsupported ones BEFORE the Critic sees the draft.

Entry points
    verify_and_repair(text, evidence, judge=None) -> (repaired_text, [claim_record dict])
        The exact signature the LangGraph Verifier node calls (once per paragraph: cover letter,
        then each screening answer). Records have keys text, label, evidence_ids, rewritten,
        removed (== agent.handoffs.Claim fields).
    verify_and_repair_detailed(text, evidence, *, judge, embedder) -> VerifyResult
        Richer: stats incl. unsupported-claim rate before and after, invented specifics, etc.
    verify_claims(draft, evidence) -> list[dict]   (label every checkable claim, no repair)

How a claim is graded (deterministic default; no LLM needed)
  1. Specifics are extracted: numbers (with unit class: %, years, money, plain), year dates and
     proper-noun phrases (client names, tools). A specific is *invented* if it is not in the
     evidence (numbers by value+unit, "N years" also by dates spans in the evidence).
  2. Support score = 0.6 * lexical coverage (content words found in the best evidence item) +
     0.4 * embedding similarity (best evidence sentence), both optional-degrading.
  3. unsupported: score < LOW (invented specifics lower the score). supported: score >= HIGH and no invented specific. Everything in
     between, or a well-supported claim with an invented specific, is partly_supported.
  Repair: unsupported -> removed. partly_supported with invented specifics -> rewritten by dropping
  the invented specifics and keeping the supported remainder (re-checked; removed if nothing
  supported remains).
An optional ``judge(claim_text, evidence) -> label | {"label", "evidence_ids"}`` (LLM judge,
injected) overrides the semantic part; invented specifics still veto "supported".

Caveat on the "after" rate: it is computed with the same checker that did the repair, so it is
close to 0 by construction. Detection quality is measured separately against labelled adversarial
drafts (rag/verify_eval.py).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from rag.text import content_words

log = logging.getLogger(__name__)

LOW, HIGH, REWRITE_MIN = 0.30, 0.55, 0.60
LABEL_RANK = {"supported": 2, "partly_supported": 1, "unsupported": 0}
Judge = Callable[[str, list[dict]], "str | dict"]

_NON_CLAIM_RE = re.compile(
    r"^(hi|hello|hey|dear|thanks|thank you|regards|best|sincerely|cheers|please|feel free|"
    r"let me know|let's|lets|happy to|glad to|looking forward|i will|i'll|i would|i'd|"
    r"i can start|i am available|i'm available|available to|do you|could you|can you|"
    r"would you|are you|which|what|how|when|why)\b", re.IGNORECASE)
_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20,
            "thirty": 30, "forty": 40, "fifty": 50}
_WORDNUM_RE = re.compile(
    r"\b(" + "|".join(_WORDNUM) + r")\b(?=\s+(?:million|billion|thousand|hundred|percent|years?|"
    r"yrs?|months?|weeks?|days?))", re.IGNORECASE)
_NUM_RE = re.compile(
    r"(?<![\w.])(?P<cur>\$)?(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
    r"(?P<unit>\s?%|\s?(?:percent|pct)\b|\s?(?:million|billion|thousand|k|m|bn)\b|"
    r"\s?(?:years?|yrs?)\b|\s?(?:months?|weeks?|days?|hours?)\b)?", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19[89]\d|20\d\d)\b")
_RANGE_RE = re.compile(r"\b(19[89]\d|20\d\d)\s*(?:-|–|—|to)\s*(19[89]\d|20\d\d|present|now)\b",
                       re.IGNORECASE)
_SINCE_RE = re.compile(r"\bsince\s+(19[89]\d|20\d\d)\b", re.IGNORECASE)
_ENTITY_RE = re.compile(
    r"\b[A-Z][\w&'.-]*(?:\s+(?:of\s+|&\s+)?[A-Z][\w&'.-]*)*")
_ENTITY_STOP = {"I", "I'm", "I've", "I'd", "I'll", "My", "We", "Our", "The", "A", "An", "In", "At",
                "On", "For", "With", "And", "But", "Also", "As", "It", "This", "That", "These",
                "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
                "January", "February", "March", "April", "May", "June", "July", "August",
                "September", "October", "November", "December", "USD", "Upwork", "Hi", "Hello",
                "Thanks", "Best", "Regards", "Dear"}
_MAG = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}


# ----------------------------------------------------------------------------- specifics
@dataclass(frozen=True)
class Number:
    value: float
    cls: str   # pct | year | time | money | plain
    span: tuple[int, int]
    raw: str


def _normalise_words(text: str) -> str:
    return _WORDNUM_RE.sub(lambda m: str(_WORDNUM[m.group(1).lower()]), text)


def extract_numbers(text: str) -> list[Number]:
    text = _normalise_words(text)
    out = []
    for m in _NUM_RE.finditer(text):
        val = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").strip().lower()
        cls = "plain"
        if unit in ("%", "percent", "pct"):
            cls = "pct"
        elif unit in ("year", "years", "yr", "yrs"):
            cls = "year"
        elif unit in ("month", "months", "week", "weeks", "day", "days", "hour", "hours"):
            cls = "time"
        elif unit in _MAG:
            val *= _MAG[unit]
        if m.group("cur"):
            cls = "money"
        if cls == "plain" and 1990 <= val <= 2099 and not unit:
            cls = "date"
        out.append(Number(val, cls, m.span(), m.group(0)))
    return out


def _years_spans(text: str, this_year: int) -> list[int]:
    spans = []
    for m in _RANGE_RE.finditer(text):
        end = this_year if m.group(2).lower() in ("present", "now") else int(m.group(2))
        spans.append(end - int(m.group(1)))
    for m in _SINCE_RE.finditer(text):
        spans.append(this_year - int(m.group(1)))
    return spans


def _entities(text: str) -> list[str]:
    ents = []
    for m in _ENTITY_RE.finditer(text):
        phrase = m.group(0).strip(".'-")
        if not phrase or phrase in _ENTITY_STOP:
            continue
        words = [w for w in phrase.split() if w not in _ENTITY_STOP]
        if m.start() == 0 and len(phrase.split()) == 1:
            continue  # sentence-initial capital, not evidence of a name
        if not words:
            continue
        ents.append(" ".join(words))
    return ents


@dataclass
class EvidenceIndex:
    items: list[dict]
    blobs: list[str]
    numbers: list[Number]
    all_text: str
    spans: list[int]
    stems: list[set[str]] = field(default_factory=list)
    windows: list[tuple[int, str]] = field(default_factory=list)  # (item idx, sentence)
    window_vecs: np.ndarray | None = None


def _blob(ev: dict) -> str:
    return " ".join([str(ev.get("title") or ""), str(ev.get("text") or ""),
                     " ".join(ev.get("skills") or [])])


def build_evidence_index(evidence: list[dict], embedder: Any | None, this_year: int
                         ) -> EvidenceIndex:
    blobs = [_blob(e) for e in evidence]
    all_text = "\n".join(blobs)
    ei = EvidenceIndex(items=evidence, blobs=blobs,
                       numbers=extract_numbers(_normalise_words(all_text)), all_text=all_text,
                       spans=_years_spans(all_text, this_year))
    ei.stems = [set(content_words(b)) for b in blobs]
    for i, e in enumerate(evidence):
        for sent in re.split(r"(?<=[.!?])\s+|\n+", str(e.get("text") or "")):
            if len(sent.split()) >= 3:
                ei.windows.append((i, sent.strip()))
        if e.get("title"):
            ei.windows.append((i, str(e["title"])))
    if embedder is not None and ei.windows:
        ei.window_vecs = embedder.encode([w for _, w in ei.windows])
    return ei


def _number_supported(num: Number, ei: EvidenceIndex) -> bool:
    for ev in ei.numbers:
        if abs(ev.value - num.value) > 1e-9 * max(1.0, abs(num.value)):
            continue
        if ev.cls == num.cls or {ev.cls, num.cls} <= {"plain", "money"}:
            return True
    if num.cls == "year":
        return any(abs(num.value - s) <= 1 for s in ei.spans)
    if num.cls == "date":
        return str(int(num.value)) in ei.all_text
    return False


def _entity_supported(entity: str, ei: EvidenceIndex) -> bool:
    low = ei.all_text.lower()
    if entity.lower() in low:
        return True
    return all(w.lower().strip("'s") in low for w in entity.split() if len(w) > 1)


def find_invented(clause: str, ei: EvidenceIndex) -> dict[str, list]:
    nums = [n for n in extract_numbers(clause) if not _number_supported(n, ei)]
    ents = [e for e in _entities(clause) if not _entity_supported(e, ei)]
    return {"numbers": nums, "entities": ents}


# ----------------------------------------------------------------------------- claim splitting
def _sentences(line: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])", line) if s.strip()]


_CLAUSE_SPLIT_RE = re.compile(r";\s+|,\s+(?:and|while|whereas)\s+(?=(?:I|we|my|our)\b)|"
                              r"\s+and\s+(?=I\s|we\s|my\s)", re.IGNORECASE)


def split_clauses(sentence: str) -> list[str]:
    parts = [p.strip() for p in _CLAUSE_SPLIT_RE.split(sentence) if p and p.strip()]
    return parts or [sentence]


def is_checkable(clause: str) -> bool:
    c = clause.strip()
    return not (len(c.split()) < 4 or c.endswith("?") or _NON_CLAIM_RE.match(c))


# ----------------------------------------------------------------------------- grading
@dataclass
class Grade:
    label: str
    score: float
    evidence_ids: list[str]
    invented: dict[str, list]
    judged: bool = False
    lex: float = 0.0


def _sim_range(embedder: Any) -> tuple[float, float]:
    return (0.10, 0.50) if str(getattr(embedder, "name", "")).startswith("hash") else (0.45, 0.80)


def grade_clause(clause: str, ei: EvidenceIndex, embedder: Any | None,
                 judge: Judge | None = None) -> Grade:
    invented = find_invented(clause, ei)
    has_invented = bool(invented["numbers"] or invented["entities"])
    words = content_words(clause)  # invented specifics stay in: they lower the coverage
    lex_per_item = [len(set(words) & st) / len(words) if words else 1.0 for st in ei.stems]
    sim_per_item = [0.0] * len(ei.items)
    if embedder is not None and ei.window_vecs is not None and len(ei.window_vecs):
        qv = embedder.encode([clause])[0]
        sims = ei.window_vecs @ qv
        for (i, _), s in zip(ei.windows, sims, strict=True):
            sim_per_item[i] = max(sim_per_item[i], float(s))
        lo, hi = _sim_range(embedder)
        simn = [float(np.clip((s - lo) / (hi - lo), 0.0, 1.0)) for s in sim_per_item]
        combined = [0.6 * lx + 0.4 * sn for lx, sn in zip(lex_per_item, simn, strict=True)]
    else:
        combined = list(lex_per_item)
    if not combined:
        return Grade("unsupported", 0.0, [], invented, lex=0.0)
    order = np.argsort(combined)[::-1]
    score = float(combined[order[0]])
    ids = [str(ei.items[i].get("id", i)) for i in order[:2] if combined[i] >= LOW]
    if score < LOW:
        label = "unsupported"
    elif has_invented or score < HIGH:
        label = "partly_supported"
    else:
        label = "supported"
    judged = False
    if judge is not None:
        verdict = judge(clause, ei.items)
        jl = verdict["label"] if isinstance(verdict, dict) else str(verdict)
        if jl in LABEL_RANK:
            judged = True
            label = jl
            if isinstance(verdict, dict) and verdict.get("evidence_ids"):
                ids = [str(x) for x in verdict["evidence_ids"]]
            if has_invented and label == "supported":
                label = "partly_supported"
    if label == "unsupported":
        ids = []
    return Grade(label, score, ids, invented, judged, float(lex_per_item[order[0]]))


# ----------------------------------------------------------------------------- rewriting
_PREP = r"(?:(?:by|of|to|for|over|about|around|nearly|almost|within|in|with|from|at)\s+)?"


def drop_invented(clause: str, invented: dict[str, list]) -> str:
    """Remove invented numbers/entities (with their dangling preposition), keep the rest."""
    out = clause
    for num in sorted(invented["numbers"], key=lambda n: -len(n.raw)):
        raw = re.escape(num.raw.strip())
        if num.cls == "year":
            out = re.sub(rf"{_PREP}{raw}(?:\s+of)?\s*", " ", out, count=1, flags=re.IGNORECASE)
        else:
            out = re.sub(rf"{_PREP}{raw}(?:\s+of\b)?\s*", " ", out, count=1, flags=re.IGNORECASE)
    for ent in invented["entities"]:
        e = re.escape(ent)
        out = re.sub(rf"(?:\b(?:called|named|at|for|with|from|by|to)\s+)?(?:(?:a|the)\s+"
                     rf"(?:client|company|customer|firm|startup)\s+(?:called|named)\s+)?{e}"
                     rf"(?:'s)?", " ", out, count=1)
    out = re.sub(r"\b(?:called|named)\s*(?=[,.;]|$)", "", out)
    out = re.sub(r"\s+([,.;])", r"\1", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;")
    out = re.sub(r"\b(?:for|with|at|of|by|to|in|from)\s*([.!?])?$", r"\1", out).strip(" ,;")
    return out


def _punct(text: str, like: str) -> str:
    end = like.strip()[-1:] if like.strip()[-1:] in ".!?" else "."
    return text if text[-1:] in ".!?" else text + end


# ----------------------------------------------------------------------------- main API
@dataclass
class VerifyResult:
    original: str
    repaired: str
    claims: list[Any]            # agent.handoffs.Claim
    stats: dict[str, Any]
    details: list[dict]          # per claim: score, invented specifics, judged


def _resolve_embedder(embedder: Any) -> Any | None:
    if embedder != "auto":
        return embedder
    try:
        from rag.embedder import get_embedder

        emb = get_embedder(allow_fallback=True)
        emb.encode(["warmup"])
        return emb
    except Exception as exc:  # noqa: BLE001
        log.warning("verify: no embedder (%s); lexical-only grounding", exc)
        return None


def _stats(grades: list[Grade]) -> dict[str, Any]:
    n = len(grades)
    unsup = sum(g.label == "unsupported" for g in grades)
    inv = sum(g.label == "unsupported" or bool(g.invented["numbers"] or g.invented["entities"])
              for g in grades)
    partly = sum(g.label == "partly_supported" for g in grades)
    return {"n_claims": n, "unsupported": unsup, "partly_supported": partly,
            "with_invented_specifics": sum(bool(g.invented["numbers"] or g.invented["entities"])
                                           for g in grades),
            "unsupported_rate": unsup / n if n else 0.0,
            "ungrounded_rate": inv / n if n else 0.0}


def verify_and_repair_detailed(text: str, evidence: list[dict], *, judge: Judge | None = None,
                               embedder: Any = "auto", this_year: int | None = None
                               ) -> VerifyResult:
    from agent.handoffs import Claim

    emb = _resolve_embedder(embedder)
    ei = build_evidence_index(evidence, emb, this_year or date.today().year)
    claims: list[Any] = []
    details: list[dict] = []
    before: list[Grade] = []
    out_lines: list[str] = []
    for line in text.split("\n"):
        out_sents: list[str] = []
        for sent in _sentences(line):
            surviving: list[str] = []
            changed = False
            for clause in split_clauses(sent):
                if not is_checkable(clause):
                    surviving.append(clause)
                    continue
                g = grade_clause(clause, ei, emb, judge)
                before.append(g)
                claim = Claim(text=clause, label=g.label, evidence_ids=g.evidence_ids)
                if g.label == "unsupported":
                    claim.removed, changed = True, True
                elif g.label == "partly_supported" and (g.invented["numbers"]
                                                        or g.invented["entities"]):
                    new = drop_invented(clause, g.invented)
                    g2 = grade_clause(new, ei, emb, judge) if len(new.split()) >= 3 else None
                    if g2 is None or g2.score < LOW or g2.lex < REWRITE_MIN:
                        claim.removed, changed = True, True
                    else:
                        claim.rewritten, changed = new, True
                        surviving.append(new)
                else:
                    surviving.append(clause)
                claims.append(claim)
                details.append({"score": g.score, "judged": g.judged,
                                "invented_numbers": [n.raw.strip() for n in g.invented["numbers"]],
                                "invented_entities": g.invented["entities"]})
            if not surviving:
                continue
            if not changed:
                out_sents.append(sent)
            else:
                joined = ", and ".join(s.rstrip(".!? ") for s in surviving)
                out_sents.append(_punct(joined, sent))
        if out_sents or not line.strip():
            out_lines.append(" ".join(out_sents))
    repaired = "\n".join(out_lines)
    after = _recheck(repaired, ei, emb, judge)
    stats = {**{f"{k}_before": v for k, v in _stats(before).items()},
             **{f"{k}_after": v for k, v in _stats(after).items()},
             "removed": sum(c.removed for c in claims),
             "rewritten": sum(c.rewritten is not None for c in claims)}
    return VerifyResult(text, repaired, claims, stats, details)


def _recheck(text: str, ei: EvidenceIndex, emb: Any | None, judge: Judge | None) -> list[Grade]:
    grades = []
    for line in text.split("\n"):
        for sent in _sentences(line):
            for clause in split_clauses(sent):
                if is_checkable(clause):
                    grades.append(grade_clause(clause, ei, emb, judge))
    return grades


def verify_and_repair(text: str, evidence: list[dict], judge: Judge | None = None
                      ) -> tuple[str, list[dict]]:
    """Graph-facing API: (repaired_text, claim_records). Called once per paragraph."""
    res = verify_and_repair_detailed(text, evidence, judge=judge)
    keys = ("text", "label", "evidence_ids", "rewritten", "removed")
    return res.repaired, [{k: c.model_dump()[k] for k in keys} for c in res.claims]


def verify_claims(draft: str, evidence: list[dict], *, judge: Judge | None = None,
                  embedder: Any = "auto") -> list[dict]:
    """Label every checkable claim (no repair)."""
    emb = _resolve_embedder(embedder)
    ei = build_evidence_index(evidence, emb, date.today().year)
    out = []
    for line in draft.split("\n"):
        for sent in _sentences(line):
            for clause in split_clauses(sent):
                if is_checkable(clause):
                    g = grade_clause(clause, ei, emb, judge)
                    out.append({"text": clause, "label": g.label, "evidence_ids": g.evidence_ids,
                                "score": g.score,
                                "invented": [n.raw.strip() for n in g.invented["numbers"]]
                                + g.invented["entities"]})
    return out
