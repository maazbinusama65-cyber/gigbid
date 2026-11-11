# review-sentiment-monitor

> app store opinion digest - repository for the consumer apps engagement.

## Features

- Uses **NLP** (see `src/`)
- Uses **Hugging Face Transformers** (see `src/`)
- Reporting queries over millions of rows
- Scripts and services in a typed, tested codebase

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/nlp_review.py`
- `src/huggingface_review.py`
- `src/sql_review.sql`

## Status

Delivered and handed over; this repository is the frozen client copy.
