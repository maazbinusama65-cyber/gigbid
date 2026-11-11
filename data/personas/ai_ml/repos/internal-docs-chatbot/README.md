# internal-docs-chatbot

> employee FAQ bot - repository for the consulting engagement.

## Features

- A question-answering layer that looks things up before it writes
- Chained prompts, tools and memory wired into one assistant
- Uses **Pinecone** (see `src/`)
- A commercial LLM endpoint behind our own thin wrapper
- Uses **Redis** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/rag_internal.py`
- `src/langchain_internal.py`
- `src/vector_db_internal.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
