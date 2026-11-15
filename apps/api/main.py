"""GigBid API application factory.

Run:  uvicorn apps.api.main:app --reload --port 8000
Env:  APP_SECRET_KEY, DATABASE_URL, GIGBID_SERVICES=mock|real, REVIEWER_EMAIL, REVIEWER_PASSWORD
"""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException

from apps.api.auth.crypto import TokenCipher
from apps.api.auth.passwords import hash_password
from apps.api.config import AppConfig, load_config
from apps.api.db import ProfileRow, UserRow, init_db, make_engine, make_session_factory
from apps.api.errors import ApiError
from apps.api.logging_setup import current_trace_id, install_logging
from apps.api.middleware import TraceIdMiddleware
from apps.api.routers import (
    analytics,
    approvals,
    health,
    jobs,
    messages,
    mock_control,
    onboarding,
    pipeline,
    proposals,
    runs,
    settings,
)
from apps.api.routers import auth as auth_router
from apps.api.services import Services, build_services

log = logging.getLogger("apps.api")


def seed_reviewer(app: FastAPI) -> None:
    """Create/refresh the preloaded reviewer account (persona ai_ml) from env credentials."""
    cfg: AppConfig = app.state.config
    if not (cfg.reviewer_email and cfg.reviewer_password):
        return
    email = cfg.reviewer_email.strip().lower()
    with app.state.session_factory() as db:
        user = db.execute(select(UserRow).where(UserRow.email == email)).scalar_one_or_none()
        if user is None:
            user = UserRow(email=email, display_name="Reviewer", password_hash="")
        user.password_hash = hash_password(cfg.reviewer_password, cfg.scrypt_n)
        user.persona_id = cfg.reviewer_persona
        user.onboarded = True
        user.is_reviewer = True
        db.add(user)
        db.commit()
        if db.execute(select(ProfileRow).where(ProfileRow.user_id == user.id)).scalar_one_or_none() is None:
            db.add(
                ProfileRow(
                    user_id=user.id, persona_id=cfg.reviewer_persona, hourly_rate_usd=65,
                    min_budget_usd=300, weekly_connects_budget=60, marketplace="gigsim",
                )
            )
            db.commit()
    log.info("reviewer account ready (persona=%s)", cfg.reviewer_persona)


def _walk_refs(node: object, out: set[str]) -> None:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
            out.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _walk_refs(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk_refs(value, out)


def add_stream_event_schema(schema: dict) -> dict:
    """Publish RunEvent (the SSE payload) so the generated client can type the stream."""
    from apps.api.schemas.runs import RunEvent

    event = RunEvent.model_json_schema(ref_template="#/components/schemas/{model}")
    event.pop("$defs", None)
    schema.setdefault("components", {}).setdefault("schemas", {})["RunEvent"] = event
    op = schema["paths"].get("/api/runs/{run_id}/stream", {}).get("get")
    if op:
        op["responses"]["200"]["content"] = {
            "text/event-stream": {"schema": {"$ref": "#/components/schemas/RunEvent"}}
        }
    return schema


def tighten_response_schemas(schema: dict) -> dict:
    """Mark every property of response-only models as required.

    The server always serialises all fields (including defaults), so the generated TypeScript types can be non-optional.
    Models that are (transitively) request bodies keep their optional fields.
    """
    components = schema.get("components", {}).get("schemas", {})
    request_roots: set[str] = set()
    for ops in schema.get("paths", {}).values():
        for op in ops.values():
            if isinstance(op, dict) and "requestBody" in op:
                _walk_refs(op["requestBody"], request_roots)
    request_side: set[str] = set()
    stack = list(request_roots)
    while stack:
        name = stack.pop()
        if name in request_side or name not in components:
            continue
        request_side.add(name)
        nested: set[str] = set()
        _walk_refs(components[name], nested)
        stack.extend(nested)
    for name, comp in components.items():
        if name in request_side or "properties" not in comp:
            continue
        comp["required"] = list(comp["properties"])
    return schema


def _error_body(error: str, detail: str) -> dict:
    return {"error": error, "detail": detail, "trace_id": current_trace_id()}


def create_app(config: AppConfig | None = None, services: Services | None = None) -> FastAPI:
    cfg = config or load_config()
    install_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        init_db(app.state.engine)
        seed_reviewer(app)
        yield

    app = FastAPI(
        title="GigBid API",
        version="0.1.0",
        description="Typed contract for the GigBid web client. Every response carries X-Trace-Id.",
        generate_unique_id_function=lambda route: route.name,
        lifespan=lifespan,
    )
    app.state.config = cfg
    app.state.engine = make_engine(cfg.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.cipher = TokenCipher(cfg.secret_key)
    app.state.services = services or build_services(cfg)

    app.add_middleware(TraceIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id"],
    )

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(_error_body(exc.error, exc.detail), status_code=exc.status_code, headers=headers)

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _error_body("http_error", str(exc.detail)), status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'] if p != 'body')}: {e['msg']}" for e in exc.errors()
        )
        body = _error_body("validation_error", detail)
        body["errors"] = jsonable_encoder(exc.errors(), custom_encoder={Exception: str})
        return JSONResponse(body, status_code=422)

    base_openapi = app.openapi

    def openapi_with_required_defaults() -> dict:
        if app.openapi_schema is None:
            app.openapi_schema = tighten_response_schemas(add_stream_event_schema(base_openapi()))
        return app.openapi_schema

    app.openapi = openapi_with_required_defaults  # type: ignore[method-assign]

    api = APIRouter(prefix="/api")
    for module in (
        auth_router, onboarding, jobs, proposals, approvals, pipeline, messages, runs, analytics, settings,
    ):
        api.include_router(module.router)
    api.include_router(health.router)
    if cfg.is_mock:
        api.include_router(mock_control.router)
    app.include_router(api)

    @app.get("/health", include_in_schema=False)
    async def root_health() -> dict:
        return {"status": "ok", "service": "gigbid-api"}

    mount_web_app(app)
    return app


def mount_web_app(app: FastAPI) -> None:
    """Serve the built React app from the same origin when GIGBID_STATIC_DIR points at it (single-container deploys).

    Registered last so every API route wins; unknown paths fall back to index.html for client-side routing, and
    anything under /api that did not match stays a JSON 404."""
    raw = os.environ.get("GIGBID_STATIC_DIR")
    if not raw or not (Path(raw) / "index.html").is_file():
        return
    root = Path(raw).resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    async def web_app(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise StarletteHTTPException(status_code=404, detail="not found")
        candidate = (root / full_path).resolve()
        if full_path and candidate.is_file() and root in candidate.parents:   # never serve outside the web root
            return FileResponse(candidate)
        return FileResponse(root / "index.html")


app = create_app()
