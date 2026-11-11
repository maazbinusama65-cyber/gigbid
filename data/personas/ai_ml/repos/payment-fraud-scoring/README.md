# payment-fraud-scoring

> chargeback early-warning - repository for the fintech engagement.

## Features

- A boosted-tree scorer that beat the logistic baseline
- Uses **scikit-learn** (see `src/`)
- A small Python web API with request validation
- Uses **Redis** (see `src/`)
- Uses **A/B testing** (see `src/`)
- A scorecard that shows where the model fails, not just one number

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/xgboost_payment.py`
- `src/sklearn_payment.py`
- `src/fastapi_payment.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
