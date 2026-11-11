# checkout-ab-test-readouts

> conversion lift verdicts - repository for the e-commerce engagement.

## Features

- Uses **A/B testing** (see `src/`)
- Careful inference instead of eyeballing charts
- A set of small automation tools
- Reporting queries over millions of rows

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/ab_testing_checkout.py`
- `src/statistics_checkout.py`
- `src/sql_checkout.sql`

## Status

Delivered and handed over; this repository is the frozen client copy.
