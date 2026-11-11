# nightly-training-pipeline

> model refresh automation - repository for the online marketplace engagement.

## Features

- Scheduled multi-step workflows with retries and backfills
- Uses **MLflow** (see `src/`)
- A reproducible image with a one-command local start
- Uses **SageMaker** (see `src/`)
- Scripts and services in a typed, tested codebase

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/airflow_nightly.py`
- `src/mlflow_nightly.py`
- `src/Dockerfile`

## Status

Delivered and handed over; this repository is the frozen client copy.
