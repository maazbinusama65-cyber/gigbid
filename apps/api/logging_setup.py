"""Trace-id context and a PII-masking log filter (emails, phones, card-like numbers, tokens)."""
from __future__ import annotations

import contextvars
import logging
import re

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def current_trace_id() -> str:
    return trace_id_var.get()


_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"(?<![\w.])(?:\d[ \-]?){13,19}(?![\w])")
_PHONE = re.compile(r"(?<![\w.])(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{2,4}\)[\s.\-]?|\d{2,4}[\s.\-])\d{3,4}[\s.\-]?\d{3,4}(?![\w])")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-~+/=]{8,}")


def mask_pii(text: str) -> str:
    """Mask emails, card-like and phone-like numbers, and bearer tokens in free text."""
    if not text:
        return text
    text = _BEARER.sub(r"\1[token]", text)
    text = _EMAIL.sub("[email]", text)
    text = _CARD.sub(lambda m: "[card]" if sum(c.isdigit() for c in m.group()) >= 13 else m.group(), text)
    text = _PHONE.sub("[phone]", text)
    return text


class PiiMaskingFilter(logging.Filter):
    """Rewrites the record message in place so every handler only ever sees masked text."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a bad format string must never break logging
            message = str(record.msg)
        record.msg = mask_pii(message)
        record.args = ()
        record.trace_id = trace_id_var.get()
        return True


_FILTER = PiiMaskingFilter()


def install_logging() -> None:
    """Attach the filter to every handler on the root and uvicorn loggers (idempotent)."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s"))
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    for name in ("", "uvicorn", "uvicorn.error", "uvicorn.access", "apps"):
        for handler in logging.getLogger(name).handlers:
            if _FILTER not in handler.filters:
                handler.addFilter(_FILTER)
