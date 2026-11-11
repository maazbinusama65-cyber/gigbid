# operations-etl-pipeline

> spreadsheets-to-database sync - repository for the logistics engagement.

## Features

- Uses **ETL** (see `src/`)
- Scripts and services in a typed, tested codebase
- Scheduled multi-step workflows with retries and backfills
- Uses **PostgreSQL** (see `src/`)
- Hand-written analytical queries with window functions

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/etl_operations.py`
- `src/airflow_operations.py`
- `src/postgres_operations.sql`

## Status

Delivered and handed over; this repository is the frozen client copy.
