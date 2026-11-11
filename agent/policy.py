"""Policy engine: platform rules as data (local YAML + rules fetched from the marketplace)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent.config_loader import ROOT

RULES_PATH = ROOT / "agent" / "policy_rules.yaml"


@dataclass
class Violation:
    rule_id: str
    description: str
    action: str
    snippet: str = ""


class Policy:
    def __init__(self, data: dict | None = None, remote_rules: list[dict] | None = None):
        if data is None:
            data = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
        self.version = str(data.get("version", "1"))
        merged: dict[str, dict] = {r["id"]: r for r in data.get("outgoing_rules", [])}
        for r in remote_rules or []:  # marketplace rules override/extend local ones by id
            rr = dict(r)
            rr.setdefault("action", "block" if rr.get("type") in ("max_words", "min_words") else "redact")
            if rr.get("type") == "forbid_regex" and "pattern" not in rr and "value" in rr:
                rr["pattern"] = rr["value"]
            merged[rr["id"]] = {**merged.get(rr["id"], {}), **rr}
        self.rules = list(merged.values())
        self.scam_signals: dict[str, list[re.Pattern]] = {
            k: [re.compile(p, re.I) for p in v] for k, v in data.get("scam_signals", {}).items()
        }

    # -- outgoing text checks --------------------------------------------------------------
    def check(self, text: str) -> list[Violation]:
        out: list[Violation] = []
        words = len(re.findall(r"\w+", text))
        for r in self.rules:
            t = r.get("type")
            if t == "forbid_regex":
                m = re.search(r["pattern"], text, re.I)
                if m:
                    out.append(Violation(r["id"], r.get("description", r["id"]), r.get("action", "redact"), m.group(0)[:60]))
            elif t == "max_words" and words > int(r["value"]):
                out.append(Violation(r["id"], r.get("description", ""), r.get("action", "block"), f"{words} words"))
            elif t == "min_words" and words < int(r["value"]):
                out.append(Violation(r["id"], r.get("description", ""), r.get("action", "block"), f"{words} words"))
            elif t == "require_phrase" and str(r["value"]).lower() not in text.lower():
                out.append(Violation(r["id"], r.get("description", ""), r.get("action", "block"), str(r["value"])))
        return out

    def clean(self, text: str) -> tuple[str, list[str]]:
        """Apply redact/rewrite actions. Returns cleaned text and the list of redactions made."""
        done: list[str] = []
        for r in self.rules:
            if r.get("type") != "forbid_regex":
                continue
            action = r.get("action", "redact")
            if action not in ("redact", "rewrite"):
                continue
            repl = r.get("replacement", "") if action == "rewrite" else ""
            new, n = re.subn(r["pattern"], repl, text, flags=re.I)
            if n:
                done.append(f"{r['id']} x{n}")
                text = re.sub(r"[ \t]{2,}", " ", new)
                text = re.sub(r"\s+([.,;!?])", r"\1", text)
        return text.strip(), done

    # -- scam signals on untrusted incoming text ----------------------------------------------
    def scam_flags(self, text: str) -> dict[str, str]:
        flags: dict[str, str] = {}
        for name, pats in self.scam_signals.items():
            for p in pats:
                m = p.search(text or "")
                if m:
                    flags[name] = m.group(0)[:60]
                    break
        return flags

    def connects_cost(self, default: int | None = None) -> int:
        for r in self.rules:
            if r.get("type") == "connects_cost":
                return int(r["value"])
        return int(default or 8)

    @classmethod
    def from_marketplace(cls, platform_policy: dict[str, Any] | None) -> Policy:
        remote = list((platform_policy or {}).get("rules", []))
        pol = cls(remote_rules=remote)
        if platform_policy and platform_policy.get("connects_per_proposal") is not None:
            pol.rules = [r for r in pol.rules if r.get("type") != "connects_cost"] + [
                {"id": "connects_cost", "type": "connects_cost", "value": int(platform_policy["connects_per_proposal"])}
            ]
        return pol


def load_policy(path: Path | None = None) -> Policy:
    if path is None:
        return Policy()
    return Policy(yaml.safe_load(path.read_text(encoding="utf-8")))
