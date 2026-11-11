"""Environment-driven settings and the editable policy (gigsim/policy.json)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    token: str = "replace_me"
    seed: int = 1337
    seed_dir: Path = ROOT / "data" / "gigsim_seed"
    policy_path: Path = PKG / "policy.json"
    state_path: str = str(ROOT / "data" / "processed" / "gigsim_state.json")  # "" = in-memory
    error_rate: float = 0.0
    error_after_commit_rate: float = 0.0
    rate_limit_rpm: int | None = None  # None -> policy.rate_limit_rpm
    require_idempotency: bool = True
    extra_jobs: str | None = None
    decision_hook: object = None  # optional callable(prefs, features, probs) -> probs
    clock_fn: object = None  # monotonic time source for the rate limiter (tests)

    @classmethod
    def from_env(cls) -> Settings:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env", override=False)
        except ImportError:
            pass
        e = os.environ
        rl = e.get("GIGSIM_RATE_LIMIT_RPM")
        return cls(
            token=e.get("GIGSIM_API_TOKEN", "replace_me"), seed=int(_f("GIGSIM_SEED", 1337)),
            seed_dir=Path(e.get("GIGSIM_SEED_DIR", ROOT / "data" / "gigsim_seed")),
            policy_path=Path(e.get("GIGSIM_POLICY_PATH", PKG / "policy.json")),
            state_path=e.get("GIGSIM_STATE_PATH", str(ROOT / "data" / "processed" / "gigsim_state.json")),
            error_rate=_f("GIGSIM_ERROR_RATE", 0.0), error_after_commit_rate=_f("GIGSIM_ERROR_AFTER_COMMIT_RATE", 0.0),
            rate_limit_rpm=int(rl) if rl else None,
            require_idempotency=e.get("GIGSIM_REQUIRE_IDEMPOTENCY", "1") not in ("0", "false", "no"),
            extra_jobs=e.get("GIGSIM_EXTRA_JOBS"))


@dataclass
class Policy:
    path: Path
    _mtime: float = -1.0
    _data: dict = field(default_factory=dict)

    def data(self) -> dict:
        try:
            m = self.path.stat().st_mtime
        except OSError:
            return self._data
        if m != self._mtime:
            self._data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m
        return self._data

    def _enabled(self) -> list[dict]:
        return [r for r in self.data().get("rules", []) if r.get("enabled", True)]

    def flat_cost(self) -> int | None:
        for r in self._enabled():
            if r["type"] == "connects_cost":
                return int(r["value"])
        return None

    def cost(self, job: dict) -> int:
        flat = self.flat_cost()
        return flat if flat is not None else int(job.get("connects_cost") or self.data().get("connects_per_proposal", 8))

    def rate_limit_rpm(self) -> int:
        return int(self.data().get("rate_limit_rpm", 60))

    def check(self, text: str) -> list[dict]:
        """Violations of enabled content rules for a cover letter (+ screening answers)."""
        out = []
        for r in self._enabled():
            t = r["type"]
            bad = ((t == "forbid_regex" and re.search(r["pattern"], text))
                   or (t == "max_words" and len(text.split()) > int(r["value"]))
                   or (t == "require_phrase" and str(r["value"]).lower() not in text.lower()))
            if bad:
                out.append({"rule_id": r["id"], "type": t, "description": r.get("description", ""),
                            "enforcement": r.get("enforcement", "reject")})
        return out

    def public(self, effective_rpm: int) -> dict:
        d = self.data()
        rules = []
        for r in self._enabled():
            rules.append({k: v for k, v in r.items() if k != "enabled"})
        flat = self.flat_cost()
        return {"version": d.get("version", 1),
                "connects_per_proposal": flat if flat is not None else d.get("connects_per_proposal", 8),
                "rules": rules, "rate_limit_rpm": effective_rpm, "fee_pct": d.get("fee_pct", 10),
                "weekly_allowance": d.get("weekly_allowance", 80)}
