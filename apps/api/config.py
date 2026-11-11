"""Environment-driven configuration. Nothing secret is hard-coded or logged."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

_DEV_FALLBACK_KEY = "dev-only-insecure-key-do-not-use-in-production"
_PLACEHOLDERS = {"", "replace_me", "changeme"}


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    app_env: str = "development"
    secret_key: str = _DEV_FALLBACK_KEY
    database_url: str = "sqlite:///./gigbid_api.db"
    services_mode: str = "mock"  # mock | real
    reviewer_email: str | None = None
    reviewer_password: str | None = None
    reviewer_persona: str = "ai_ml"
    session_ttl_hours: int = 24 * 7
    scrypt_n: int = 2**14
    max_upload_bytes: int = 10 * 1024 * 1024
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    mock_delay_ms: int = 350
    trace_url_template: str = "http://localhost:6006/trace/{trace_id}"
    login_max_failures: int = 8
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"prod", "production"}

    @property
    def is_mock(self) -> bool:
        return self.services_mode == "mock"


def load_config() -> AppConfig:
    app_env = os.environ.get("APP_ENV", "development")
    key = os.environ.get("APP_SECRET_KEY", "")
    prod = app_env.lower() in {"prod", "production"}
    if key.strip() in _PLACEHOLDERS:
        if prod:
            raise RuntimeError("APP_SECRET_KEY must be set to a real secret in production")
        key = _DEV_FALLBACK_KEY
    origins = os.environ.get("CORS_ORIGINS")
    cfg = AppConfig(
        app_env=app_env,
        secret_key=key,
        database_url=os.environ.get("DATABASE_URL") or "sqlite:///./gigbid_api.db",
        services_mode=os.environ.get("GIGBID_SERVICES", "mock").strip().lower(),
        reviewer_email=os.environ.get("REVIEWER_EMAIL") or None,
        reviewer_password=os.environ.get("REVIEWER_PASSWORD") or None,
        reviewer_persona=os.environ.get("REVIEWER_PERSONA", "ai_ml"),
        session_ttl_hours=int(os.environ.get("SESSION_TTL_HOURS", 24 * 7)),
        scrypt_n=int(os.environ.get("PASSWORD_SCRYPT_N", 2**14)),
        max_upload_bytes=int(os.environ.get("MAX_UPLOAD_BYTES", 10 * 1024 * 1024)),
        cors_origins=tuple(o.strip() for o in origins.split(",")) if origins else AppConfig.cors_origins,
        mock_delay_ms=int(os.environ.get("MOCK_STREAM_DELAY_MS", 350)),
        trace_url_template=os.environ.get("TRACE_URL_TEMPLATE", AppConfig.trace_url_template),
        login_max_failures=int(os.environ.get("LOGIN_MAX_FAILURES", 8)),
    )
    return cfg
