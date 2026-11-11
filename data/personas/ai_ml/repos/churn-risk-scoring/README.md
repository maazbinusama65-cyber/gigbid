# churn-risk-scoring

> who-will-cancel model - repository for the subscription media engagement.

## Features

- Classical models with cross-validated pipelines
- A boosted-tree scorer that beat the logistic baseline
- Uses **pandas** (see `src/`)
- Every training run logged with its parameters and metrics
- Uses **A/B testing** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/sklearn_churn.py`
- `src/xgboost_churn.py`
- `src/pandas_churn.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
