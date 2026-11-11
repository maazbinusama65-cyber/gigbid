"""scrypt password hashing with per-user salt; constant-time verification."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

_R = 8
_P = 1
_DKLEN = 32
_MAXMEM = 128 * 1024 * 1024


def hash_password(password: str, n: int = 2**14) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=n, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM
    )
    return f"scrypt${n}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=int(n), r=int(r), p=int(p),
            dklen=len(expected), maxmem=_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# Verified against when the e-mail is unknown, to equalise response timing.
DUMMY_HASH = hash_password("not-a-real-password", n=2**14)
