# Runbook

## Run locally
```
make seed            # deterministic personas + jobs + gold labels
make gigsim          # simulator :8081
make api             # FastAPI :8000 (GIGBID_SERVICES=real)
make web             # Vite :5173
# or: cp .env.example .env && docker compose -f infra/docker-compose.yml up --build
```

## Scheduling (E1)
Each saved search has a schedule. Defaults: GigSim every 15 min (simulated, cheap); **live Upwork every
240 min** (`marketplace.live_poll_interval_minutes`). Justification: Upwork treats scraping and bot-like polling
as violations; a freelancer reading a feed a few times per working day is human-like, new jobs are time
sensitive only on the scale of hours, and every poll costs one authenticated read through the official MCP
server. The scheduler adds jitter and never polls faster than the configured interval.
Idempotency: a job is processed on thread `bid:<user>:<job>`; a restarted worker finds the checkpoint and resumes
instead of re-analysing; submission is idempotent at the marketplace (see ADR 4).

## Degraded mode
Marketplace MCP down -> tool calls raise `ToolUnavailable`, thread becomes `needs_attention`
(`marketplace_unavailable`), `/api/health` reports `marketplace.ok=false`, the UI shows the banner and the
worker re-queues with backoff. Restart the server and press Retry (or wait for the next sweep).

## Crash during approval
Kill the API while a proposal waits: the checkpoint is in Postgres (sqlite file in dev). Restart, open the
approval (`/api/approvals`), approve: the graph resumes from the interrupt and submits once.

## Secrets
Environment only (`.env.example` lists names). OAuth tokens are Fernet-encrypted with `APP_SECRET_KEY`.
