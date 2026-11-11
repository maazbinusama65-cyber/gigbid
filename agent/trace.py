"""Execution trace (kept apart from graph state and from memory).

One JSONL file per run (data/processed/traces/<run_id>.jsonl) plus an in-memory subscriber list so
the API can stream events to the UI. Everything is PII-masked on write. A `trace_id` flows from the UI
request -> API -> graph -> tools -> audit log (E3).
"""
from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent.config_loader import ROOT
from agent.guardrails import mask_obj

TRACE_DIR = ROOT / "data" / "processed" / "traces"
_current_trace: contextvars.ContextVar[str | None] = contextvars.ContextVar("gigbid_trace_id", default=None)


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


def current_trace_id() -> str | None:
    return _current_trace.get()


def set_trace_id(tid: str | None):
    return _current_trace.set(tid)


class TraceRecorder:
    def __init__(self, run_id: str, trace_dir: Path | None = None):
        self.run_id = run_id
        self.dir = trace_dir or TRACE_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in run_id)  # ':' is illegal on Windows
        self.path = self.dir / f"{safe}.jsonl"
        self._lock = threading.Lock()
        self.subscribers: list[Callable[[dict], None]] = []

    def event(self, type_: str, node: str | None = None, **data: Any) -> dict:
        rec = {"ts": time.time(), "run_id": self.run_id, "trace_id": current_trace_id() or self.run_id,
               "type": type_, "node": node, "data": mask_obj(data)}
        with self._lock, open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        for cb in list(self.subscribers):
            try:
                cb(rec)
            except Exception:  # a broken subscriber must never break the graph
                pass
        return rec

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_trace(run_id: str, trace_dir: Path | None = None) -> list[dict]:
    return TraceRecorder(run_id, trace_dir).read()
