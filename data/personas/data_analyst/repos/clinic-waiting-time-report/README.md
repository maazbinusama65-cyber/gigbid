# clinic-waiting-time-report

> queue length insights - repository for the healthcare engagement.

## Features

- Hand-written analytical queries with window functions
- Uses **Tableau** (see `src/`)
- Careful inference instead of eyeballing charts
- Deduplicated, standardised records from messy exports

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/sql_clinic.sql`
- `src/tableau_clinic.sql`
- `src/statistics_clinic.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
