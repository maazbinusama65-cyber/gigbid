"""Core data types for the RAG package."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

DOC_TYPES = ("cv", "case_study", "readme", "code", "review", "proposal", "summary")
OUTCOMES = ("won", "replied", "ignored")


@dataclass
class Document:
    """One ingestible source document with the metadata every chunk inherits (B1)."""

    doc_id: str
    persona: str
    type: str
    text: str
    title: str = ""
    source: str = ""
    project_id: str | None = None
    project_ids: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    date: str | None = None
    client_industry: str | None = None
    outcome: str | None = None  # proposals only: won | replied | ignored
    project_title: str = ""  # filled by the loader from the project fact sheet
    extra: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        """Stable hash over text AND metadata so a metadata edit also triggers re-indexing."""
        payload = json.dumps(asdict(self), sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


# Keys returned for every evidence item (contract, INTERFACES section 4).
RESULT_KEYS = ("id", "project_id", "type", "source", "title", "text", "date", "outcome",
               "skills", "score")
