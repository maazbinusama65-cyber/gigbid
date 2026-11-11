# sales-email-copilot

> reply suggestion tool - repository for the b2b sales engagement.

## Features

- A commercial LLM endpoint behind our own thin wrapper
- Uses **prompt engineering** (see `src/`)
- Chained prompts, tools and memory wired into one assistant
- A typed async HTTP service with auto-generated docs
- Uses **Redis** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/openai_api_sales.py`
- `src/prompt_eng_sales.py`
- `src/langchain_sales.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
