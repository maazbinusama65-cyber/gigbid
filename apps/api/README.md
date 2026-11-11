# GigBid API (FastAPI)

Prefix `/api`, opaque bearer sessions, every response carries `X-Trace-Id`. The OpenAPI document is the
contract for the web client (`apps/web/src/lib/api/schema.d.ts` is generated from it).

```
main.py            app factory, error handlers, OpenAPI tweaks (all response fields required)
routers/           auth, onboarding, jobs, proposals, approvals, pipeline, messages, runs,
                   analytics, settings (+ memory, connections), health, mock_control (mock only)
streaming.py       SSE bridge: services.stream_run -> text/event-stream
auth/              scrypt passwords, hashed opaque sessions, Fernet-encrypted OAuth token store
schemas/           request/response models (agent objects are reused from agent.handoffs)
services.py        the `Services` Protocol: the only thing routers call
mock_services.py   fixture-backed implementation (default); mock_data.py holds the fixtures
real_services.py   RealServices (written by the agent-core owner) behind the same Protocol
db.py              SQLAlchemy models (sqlite default, DATABASE_URL for Postgres)
middleware.py      pure-ASGI trace-id middleware;  logging_setup.py: PII-masking log filter
```

## Run

```bash
export APP_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
export REVIEWER_EMAIL=reviewer@example.com REVIEWER_PASSWORD='choose-one'   # seeds a persona ai_ml account
GIGBID_SERVICES=mock uvicorn apps.api.main:app --reload --port 8000          # mock | real
python -m apps.api.export_openapi                                            # writes apps/web/openapi.json
python -m pytest tests/unit/test_api_*.py -q
```

Environment: `APP_SECRET_KEY` (required when `APP_ENV=production`; keys the OAuth token cipher),
`DATABASE_URL`, `GIGBID_SERVICES`, `REVIEWER_EMAIL`/`REVIEWER_PASSWORD`/`REVIEWER_PERSONA`,
`SESSION_TTL_HOURS`, `MOCK_STREAM_DELAY_MS`, `TRACE_URL_TEMPLATE` (e.g. a Langfuse URL with `{trace_id}`),
`CORS_ORIGINS`.

## SSE event contract

`GET /api/runs/{id}/stream` sends one JSON object per event:
`{type: node_start|node_end|interrupt|token|done|error|degraded, node, ts, data}`.
The server replays history on reconnect. The browser reads it with `fetch` so the bearer token stays in a header.
Run statuses: running, awaiting_approval, submitted, skipped, rejected, blocked, needs_attention, dead_letter.

## Mock-only controls (hidden from OpenAPI)

`POST /api/_mock/degrade {"degraded": true}` simulates a marketplace outage; `POST /api/_mock/reset` restores fixtures.
