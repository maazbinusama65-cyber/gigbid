"""Append-only JSONL audit log with a hash chain (tamper evidence).

One record per tool call: ts, user, tool, arguments (PII-masked), result summary, trace_id, ok.
The file is only ever opened in append mode; each record carries ``prev`` (hash of the previous
line) and ``hash`` so edits or deletions are detectable by :func:`verify_chain`.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from .pii import mask_value

GENESIS = "0" * 16


def _digest(prev: str, body: str) -> str:
    return hashlib.sha256((prev + body).encode()).hexdigest()[:16]


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return GENESIS
        last = GENESIS
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line).get("hash", last)
                    except json.JSONDecodeError:
                        continue
        return last

    def record(
        self,
        *,
        user: str,
        tool: str,
        arguments: dict[str, Any],
        result_summary: str,
        trace_id: str | None,
        ok: bool,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "user": user,
            "tool": tool,
            "arguments": mask_value(arguments),
            "result": mask_value(result_summary, max_len=300),
            "trace_id": trace_id,
            "ok": ok,
        }
        if extra:
            entry.update(extra)
        with self._lock:
            body = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            entry["prev"] = self._last
            entry["hash"] = _digest(self._last, body)
            with self.path.open("a", encoding="utf-8") as fh:  # append-only
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._last = entry["hash"]
        return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            return [json.loads(ln) for ln in fh if ln.strip()]


def verify_chain(path: str | Path) -> bool:
    prev = GENESIS
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        h, p = e.pop("hash"), e.pop("prev")
        if p != prev or _digest(prev, json.dumps(e, sort_keys=True, ensure_ascii=False)) != h:
            return False
        prev = h
    return True
