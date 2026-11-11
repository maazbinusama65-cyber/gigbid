# analytics-warehouse-dbt

> single source of truth models - repository for the saas engagement.

## Features

- Uses **dbt** (see `src/`)
- Elastic warehouse sizes switched per workload
- Hand-written analytical queries with window functions
- Uses **dimensional modeling** (see `src/`)
- Uses **Airflow** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/dbt_analytics.sql`
- `src/snowflake_analytics.sql`
- `src/sql_analytics.sql`

## Status

Delivered and handed over; this repository is the frozen client copy.
