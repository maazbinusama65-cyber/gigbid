"""Long-term memory on a LangGraph store: style memory + outcome memory (C2, R7).

Namespaces
  ("staging","style",user)    observations derived from edits (patterns + counts) - NOT memory yet
  ("staging","outcome",user)  per (category, feature) reply counters - NOT memory yet
  ("memory","style",user)     promoted style rules      -> shown in Settings > Memory, deletable
  ("memory","outcome",user)   promoted outcome insights -> shown in Settings > Memory, deletable
"""
from __future__ import annotations

import difflib
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from agent.config_loader import ROOT, Config, load_config
from agent.memory.promotion_rules import should_promote_outcome, should_promote_style_edit

_TONE_PHRASES = [
    "passionate", "excited", "thrilled", "dear sir", "dear hiring manager", "hope this finds you well",
    "i am writing to", "i am the perfect", "perfect fit", "rockstar", "ninja", "guru", "synergy",
    "i would love the opportunity", "esteemed",
]


def make_store(path: str | Path | None = None) -> BaseStore:
    """Durable sqlite-backed LangGraph store (falls back to in-memory when path is ':memory:')."""
    if path == ":memory:":
        return InMemoryStore()
    from langgraph.store.sqlite import SqliteStore

    p = Path(path) if path else ROOT / "data" / "processed" / "memory.sqlite"
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, isolation_level=None)
    store = SqliteStore(conn)
    store.setup()
    return store


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def analyze_edit(original: str, edited: str) -> list[dict]:
    """Derive pattern observations from a user's edit. Deterministic; no model involved."""
    obs: list[dict] = []
    o_s, e_s = _sentences(original), _sentences(edited)
    if o_s and e_s and o_s[0] not in e_s:
        obs.append({"pattern": "drop_opening", "text": "Cut the generic first sentence; open with the client's problem."})
    o_l, e_l = original.lower(), edited.lower()
    for ph in _TONE_PHRASES:
        if ph in o_l and ph not in e_l:
            obs.append({"pattern": f"avoid:{ph}", "text": f"Never use the phrase '{ph}'."})
    ow, ew = len(original.split()), len(edited.split())
    if ow and ew < 0.85 * ow:
        obs.append({"pattern": "shorter", "text": f"Keep proposals shorter (the user trims drafts to about {ew} words)."})
    if edited.strip().endswith("?") and not original.strip().endswith("?"):
        obs.append({"pattern": "end_question", "text": "End with one specific question to the client."})
    if not o_s:
        return obs
    # sentence-level deletions that look like filler (very short sentence removed)
    sm = difflib.SequenceMatcher(a=o_s, b=e_s)
    removed = [o_s[i] for tag, i1, i2, _, _ in sm.get_opcodes() if tag == "delete" for i in range(i1, i2)]
    if len(removed) >= 2:
        obs.append({"pattern": "cut_filler", "text": "Remove filler sentences that do not cite evidence."})
    return obs


def proposal_features(text: str, price_ratio: float | None = None) -> dict[str, bool]:
    words = len(text.split())
    return {
        "asks_question": "?" in text,
        "cites_project": bool(re.search(r"\b(built|shipped|delivered|led|designed|implemented)\b", text, re.I)),
        "short": words <= 150,
        "has_numbers": bool(re.search(r"\b\d+(?:\.\d+)?\s?(%|x|ms|k|users|rows|hours|weeks)\b", text, re.I)),
        "below_median_price": bool(price_ratio is not None and price_ratio <= 1.0),
    }


class LongTermMemory:
    def __init__(self, store: BaseStore | None = None, cfg: Config | None = None):
        self.store = store or make_store(":memory:")
        cfg = cfg or load_config()
        self.style_rule = cfg["memory"]["style_promotion"]
        self.outcome_rule = cfg["memory"]["outcome_promotion"]

    # -- style -------------------------------------------------------------------------------
    def record_edit(self, user_id: str, job_id: str, original: str, edited: str) -> list[dict]:
        promoted: list[dict] = []
        for ob in analyze_edit(original, edited):
            ns = ("staging", "style", user_id)
            cur = self.store.get(ns, ob["pattern"])
            v = cur.value if cur else {"pattern": ob["pattern"], "text": ob["text"], "count": 0, "jobs": []}
            v["count"] += 1
            if job_id not in v["jobs"]:
                v["jobs"].append(job_id)
            self.store.put(ns, ob["pattern"], v)
            if should_promote_style_edit(v["count"], True, len(v["jobs"]),
                                         self.style_rule["min_edits"], self.style_rule["min_distinct_jobs"]):
                promoted.append(self._promote("style", user_id, ob["pattern"], v["text"],
                                              {"count": v["count"], "jobs": v["jobs"]}))
        return [p for p in promoted if p]

    def _promote(self, kind: str, user_id: str, key: str, text: str, evidence: dict) -> dict | None:
        ns = ("memory", kind, user_id)
        if self.store.get(ns, key):
            return None  # already promoted
        item = {"id": key, "kind": kind, "text": text, "evidence": evidence, "created_at": time.time(),
                "rule": "style_promotion" if kind == "style" else "outcome_promotion"}
        self.store.put(ns, key, item)
        return item

    def style_rules(self, user_id: str) -> list[str]:
        return [i.value["text"] for i in self.store.search(("memory", "style", user_id))]

    # -- outcome -----------------------------------------------------------------------------
    def record_outcome(self, user_id: str, category: str, features: dict[str, bool], replied: bool) -> list[dict]:
        ns = ("staging", "outcome", user_id)
        for name, present in features.items():
            key = f"{category}:{name}"
            cur = self.store.get(ns, key)
            v = cur.value if cur else {"category": category, "feature": name, "with": [0, 0], "without": [0, 0]}
            side = v["with" if present else "without"]
            side[0] += 1
            side[1] += int(replied)
            self.store.put(ns, key, v)
        return self.promote_outcomes(user_id, category)

    def promote_outcomes(self, user_id: str, category: str) -> list[dict]:
        out = []
        for it in self.store.search(("staging", "outcome", user_id)):
            v = it.value
            if v["category"] != category:
                continue
            (nw, rw), (nn, rn) = v["with"], v["without"]
            if should_promote_outcome(nw, rw, nn, rn, self.outcome_rule["min_samples"],
                                      self.outcome_rule["min_reply_rate_delta"]):
                text = (f"In '{category}', proposals with '{v['feature']}' got replies {rw}/{nw} "
                        f"vs {rn}/{nn} without.")
                p = self._promote("outcome", user_id, it.key, text, {"with": v["with"], "without": v["without"]})
                if p:
                    out.append(p)
        return out

    def outcome_hints(self, user_id: str, category: str) -> list[str]:
        return [i.value["text"] for i in self.store.search(("memory", "outcome", user_id))
                if i.key.startswith(f"{category}:")]

    # -- viewer (Settings > Memory) ----------------------------------------------------------
    def list_all(self, user_id: str) -> list[dict]:
        items = []
        for kind in ("style", "outcome"):
            items += [{**i.value, "id": f"{kind}:{i.key}"} for i in self.store.search(("memory", kind, user_id))]
        return sorted(items, key=lambda x: -x.get("created_at", 0))

    def delete(self, user_id: str, item_id: str) -> bool:
        kind, _, key = item_id.partition(":")
        if kind not in ("style", "outcome") or not self.store.get(("memory", kind, user_id), key):
            return False
        self.store.delete(("memory", kind, user_id), key)
        if kind == "style":  # deleting a rule also resets its staging counter so it must be re-earned
            self.store.delete(("staging", "style", user_id), key)
        return True


def new_id() -> str:
    return uuid.uuid4().hex[:12]


Any  # re-exported typing marker for linters
