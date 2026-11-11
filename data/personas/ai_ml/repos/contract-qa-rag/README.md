# contract-qa-rag

> clause finder for the deal team - repository for the legal tech engagement.

## Features

- A question-answering layer that looks things up before it writes
- Dense vector representations of text for nearest-neighbour lookup
- A hosted similarity-search store with metadata filters
- Uses **LangChain** (see `src/`)
- Uses **OpenAI API** (see `src/`)
- A typed async HTTP service with auto-generated docs

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/rag_contract.py`
- `src/embeddings_contract.py`
- `src/vector_db_contract.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
