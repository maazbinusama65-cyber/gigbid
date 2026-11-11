"""Fernet encryption for OAuth tokens. Key derives from APP_SECRET_KEY; plaintext is never logged."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    def __init__(self, secret_key: str) -> None:
        derived = hashlib.sha256(("gigbid-oauth-v1:" + secret_key).encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str | None:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken:
            return None
