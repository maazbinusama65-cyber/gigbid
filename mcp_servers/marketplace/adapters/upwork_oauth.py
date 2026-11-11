"""OAuth 2.1 (authorization code + PKCE) helpers and an encrypted per-user token store.

NOTE: not exercised against the real Upwork authorization server (no credentials in this
project); the flow follows the MCP authorization spec (RFC 9728 / RFC 8414 discovery, RFC 7636
PKCE) and is unit-tested with a mocked HTTP transport. Tokens are never logged or repr'd.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PLACEHOLDER_SECRETS = {"", "replace_me", "changeme", "secret"}


class OAuthError(Exception):
    """Raised for protocol failures. Messages never contain token values."""


# --------------------------------------------------------------------------- PKCE
def generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, S256 code_challenge)."""
    verifier = secrets.token_urlsafe(64)[:96]  # 43-128 chars per RFC 7636
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorization_url(authorize_endpoint: str, client_id: str, redirect_uri: str, state: str,
                            code_challenge: str, scope: str | None = None,
                            resource: str | None = None) -> str:
    q = {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri,
         "state": state, "code_challenge": code_challenge, "code_challenge_method": "S256"}
    if scope:
        q["scope"] = scope
    if resource:
        q["resource"] = resource  # RFC 8707 audience binding, required by the MCP spec
    return f"{authorize_endpoint}?{urlencode(q)}"


# --------------------------------------------------------------------------- tokens
@dataclass
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: float = 0.0
    scope: str | None = None

    def is_expired(self, skew: float = 60.0, now: float | None = None) -> bool:
        return self.expires_at and (now or time.time()) >= self.expires_at - skew

    def to_json(self) -> str:
        return json.dumps({"a": self.access_token, "r": self.refresh_token, "e": self.expires_at,
                           "s": self.scope})

    @classmethod
    def from_json(cls, raw: str) -> TokenSet:
        d = json.loads(raw)
        return cls(d["a"], d.get("r"), d.get("e", 0.0), d.get("s"))

    @classmethod
    def from_response(cls, body: dict[str, Any], previous_refresh: str | None = None,
                      now: float | None = None) -> TokenSet:
        if "access_token" not in body:
            raise OAuthError("token endpoint response had no access_token")
        exp = (now or time.time()) + float(body.get("expires_in", 3600))
        return cls(body["access_token"], body.get("refresh_token") or previous_refresh, exp,
                   body.get("scope"))


async def _post_token(token_endpoint: str, data: dict[str, str],
                      http: httpx.AsyncClient | None) -> dict[str, Any]:
    own = http is None
    client = http or httpx.AsyncClient(timeout=15)
    try:
        resp = await client.post(token_endpoint, data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise OAuthError(f"token endpoint unreachable: {type(exc).__name__}") from exc
    finally:
        if own:
            await client.aclose()
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", "unknown_error")
        except ValueError:
            err = "unknown_error"
        raise OAuthError(f"token endpoint returned {resp.status_code}: {err}")
    return resp.json()


async def exchange_code(token_endpoint: str, *, client_id: str, code: str, code_verifier: str,
                        redirect_uri: str, client_secret: str | None = None,
                        http: httpx.AsyncClient | None = None) -> TokenSet:
    data = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client_id, "code_verifier": code_verifier}
    if client_secret:
        data["client_secret"] = client_secret
    return TokenSet.from_response(await _post_token(token_endpoint, data, http))


async def refresh_tokens(token_endpoint: str, *, client_id: str, tokens: TokenSet,
                         client_secret: str | None = None,
                         http: httpx.AsyncClient | None = None) -> TokenSet:
    if not tokens.refresh_token:
        raise OAuthError("no refresh token; the user must reconnect Upwork")
    data = {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token, "client_id": client_id}
    if client_secret:
        data["client_secret"] = client_secret
    return TokenSet.from_response(await _post_token(token_endpoint, data, http),
                                  previous_refresh=tokens.refresh_token)


async def discover_endpoints(resource_url: str, http: httpx.AsyncClient | None = None) -> dict[str, str]:
    """RFC 9728 protected-resource metadata -> RFC 8414 authorization-server metadata."""
    origin = "/".join(resource_url.split("/")[:3])
    own = http is None
    client = http or httpx.AsyncClient(timeout=15)
    try:
        prm = (await client.get(f"{origin}/.well-known/oauth-protected-resource")).json()
        issuer = prm["authorization_servers"][0].rstrip("/")
        meta = (await client.get(f"{issuer}/.well-known/oauth-authorization-server")).json()
        return {"authorize": meta["authorization_endpoint"], "token": meta["token_endpoint"],
                "registration": meta.get("registration_endpoint", "")}
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        raise OAuthError(f"OAuth discovery failed: {type(exc).__name__}") from exc
    finally:
        if own:
            await client.aclose()


# --------------------------------------------------------------------------- encrypted store
def fernet_from_secret(secret: str) -> Fernet:
    if secret in PLACEHOLDER_SECRETS or len(secret) < 16:
        raise OAuthError("APP_SECRET_KEY must be set to a real secret (>= 16 chars) to store tokens")
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"gigbid-token-store-v1",
               info=b"upwork-oauth").derive(secret.encode())
    return Fernet(base64.urlsafe_b64encode(key))


class EncryptedTokenStore:
    """Per-user token storage; values are Fernet-encrypted with a key derived from APP_SECRET_KEY."""

    def __init__(self, path: str | Path, secret: str | None = None) -> None:
        self.path = Path(path)
        self._fernet = fernet_from_secret(secret if secret is not None else os.getenv("APP_SECRET_KEY", ""))
        self._lock = threading.Lock()

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8") or "{}")

    def _save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".tok")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.path)

    def put(self, user: str, tokens: TokenSet) -> None:
        with self._lock:
            data = self._load()
            data[user] = self._fernet.encrypt(tokens.to_json().encode()).decode()
            self._save(data)

    def get(self, user: str) -> TokenSet | None:
        with self._lock:
            raw = self._load().get(user)
        if raw is None:
            return None
        try:
            return TokenSet.from_json(self._fernet.decrypt(raw.encode()).decode())
        except InvalidToken as exc:
            raise OAuthError("stored token could not be decrypted (APP_SECRET_KEY changed?)") from exc

    def delete(self, user: str) -> None:
        with self._lock:
            data = self._load()
            if data.pop(user, None) is not None:
                self._save(data)


# --------------------------------------------------------------------------- flow orchestration
@dataclass
class OAuthConfig:
    client_id: str
    authorize_endpoint: str
    token_endpoint: str
    redirect_uri: str
    scope: str | None = None
    resource: str | None = "https://mcp.upwork.com/mcp"
    client_secret: str | None = field(default=None, repr=False)


class AuthFlow:
    """Start a user's connect flow and complete it from the redirect callback."""

    def __init__(self, cfg: OAuthConfig, store: EncryptedTokenStore, ttl: float = 600.0) -> None:
        self.cfg, self.store, self.ttl = cfg, store, ttl
        self._pending: dict[str, tuple[str, str, float]] = {}

    def start(self, user: str) -> str:
        state = secrets.token_urlsafe(24)
        verifier, challenge = generate_pkce()
        self._pending[state] = (user, verifier, time.time() + self.ttl)
        return build_authorization_url(self.cfg.authorize_endpoint, self.cfg.client_id,
                                       self.cfg.redirect_uri, state, challenge, self.cfg.scope,
                                       self.cfg.resource)

    async def complete(self, state: str, code: str, http: httpx.AsyncClient | None = None) -> str:
        entry = self._pending.pop(state, None)
        if entry is None or entry[2] < time.time():
            raise OAuthError("unknown or expired OAuth state")
        user, verifier, _ = entry
        tokens = await exchange_code(self.cfg.token_endpoint, client_id=self.cfg.client_id, code=code,
                                     code_verifier=verifier, redirect_uri=self.cfg.redirect_uri,
                                     client_secret=self.cfg.client_secret, http=http)
        self.store.put(user, tokens)
        return user
