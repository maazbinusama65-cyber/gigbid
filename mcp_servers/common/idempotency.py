"""Durable idempotency + ownership store (SQLite, survives process restart).

A write is identified by (user, tool, idempotency_key). The first successful execution stores the
result and a fingerprint of the arguments; a retry with the same key returns the stored result
without touching the marketplace again. Same key with different arguments is a conflict.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any


class IdempotencyConflict(Exception):
    pass


def fingerprint(args: dict[str, Any]) -> str:
    blob = json.dumps(args, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class IdempotencyStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        with self._lock, self._db:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS idem (user TEXT, tool TEXT, key TEXT, fp TEXT,"
                " result TEXT, PRIMARY KEY (user, tool, key))"
            )
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS owner (kind TEXT, id TEXT, user TEXT,"
                " PRIMARY KEY (kind, id))"
            )

    def get(self, user: str, tool: str, key: str, fp: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT fp, result FROM idem WHERE user=? AND tool=? AND key=?", (user, tool, key)
            ).fetchone()
        if row is None:
            return None
        if row[0] != fp:
            raise IdempotencyConflict(
                "idempotency_conflict: this idempotency_key was already used with different "
                "arguments"
            )
        return json.loads(row[1])

    def put(self, user: str, tool: str, key: str, fp: str, result: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO idem VALUES (?,?,?,?,?)",
                (user, tool, key, fp, json.dumps(result, default=str)),
            )

    def set_owner(self, kind: str, obj_id: str, user: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO owner VALUES (?,?,?)", (kind, obj_id, user))

    def owner(self, kind: str, obj_id: str) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT user FROM owner WHERE kind=? AND id=?", (kind, obj_id)
            ).fetchone()
        return row[0] if row else None

    def close(self) -> None:
        with self._lock:
            self._db.close()
