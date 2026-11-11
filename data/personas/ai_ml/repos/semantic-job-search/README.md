# semantic-job-search

> resume-to-role finder - repository for the hr tech engagement.

## Features

- Uses **embeddings** (see `src/`)
- A hosted similarity-search store with metadata filters
- Text understanding for messy free-form customer messages
- Uses **FastAPI** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/embeddings_semantic.py`
- `src/vector_db_semantic.py`
- `src/nlp_semantic.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
