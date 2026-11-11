# product-usage-bigquery

> event data reporting - repository for the saas engagement.

## Features

- Uses **BigQuery** (see `src/`)
- Reporting queries over millions of rows
- Free shareable web dashboards connected to live sheets and warehouse tables
- Uses **data cleaning** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/bigquery_product.sql`
- `src/sql_product.sql`
- `src/data_cleaning_product.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
