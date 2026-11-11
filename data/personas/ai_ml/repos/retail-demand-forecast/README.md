# retail-demand-forecast

> weekly sales predictor - repository for the retail engagement.

## Features

- Forward-looking numbers built from past daily history
- A set of small automation tools
- Scripted reshaping of large spreadsheets into tidy tables
- Scheduled multi-step workflows with retries and backfills
- A relational store with proper indexes and migrations

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/timeseries_retail.py`
- `src/pandas_retail.py`
- `src/airflow_retail.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
