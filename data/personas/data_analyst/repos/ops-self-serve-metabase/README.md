# ops-self-serve-metabase

> internal BI portal - repository for the logistics engagement.

## Features

- An internal self-service BI portal over the database
- Uses **SQL** (see `src/`)
- Uses **PostgreSQL** (see `src/`)
- A one-page scorecard that leadership reads on Monday

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/sql_ops.sql`
- `src/postgres_ops.sql`
- `src/kpi_dashboards_ops.sql`

## Status

Delivered and handed over; this repository is the frozen client copy.
