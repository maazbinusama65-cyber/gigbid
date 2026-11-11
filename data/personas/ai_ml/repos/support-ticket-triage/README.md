# support-ticket-triage

> helpdesk auto-labeller - repository for the saas engagement.

## Features

- A set of small automation tools
- Uses **Hugging Face Transformers** (see `src/`)
- Text understanding for messy free-form customer messages
- A small Python web API with request validation
- Containerised builds that run the same on every machine
- Uses **MLflow** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/huggingface_support.py`
- `src/nlp_support.py`
- `src/fastapi_support.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
