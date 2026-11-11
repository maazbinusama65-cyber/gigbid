"""PII / secret masking for audit logs and traces. Pure functions, no I/O."""
from __future__ import annotations

import re
from typing import Any

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{8,}\d)(?!\w)")
_TOKEN = re.compile(r"\b(?:gsk_|sk-|ghp_|gho_|github_pat_|xox[bp]-|AKIA)[A-Za-z0-9_\-]{8,}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_KEYS = re.compile(r"(?i)(token|secret|password|authorization|api[_-]?key|cookie)")

MAX_STR = 200


def mask_text(text: str, max_len: int = MAX_STR) -> str:
    out = _BEARER.sub("[token]", text)
    out = _TOKEN.sub("[token]", out)
    out = _EMAIL.sub("[email]", out)
    out = _PHONE.sub("[phone]", out)
    if len(out) > max_len:
        out = out[:max_len] + f"...[+{len(out) - max_len} chars]"
    return out


def mask_value(value: Any, key: str = "", max_len: int = MAX_STR) -> Any:
    """Recursively mask strings; secret-looking keys are fully redacted; long text is truncated."""
    if key and _SECRET_KEYS.search(key):
        return "[redacted]"
    if isinstance(value, str):
        return mask_text(value, max_len)
    if isinstance(value, dict):
        return {str(k): mask_value(v, str(k), max_len) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask_value(v, key, max_len) for v in value[:20]]
    return value
