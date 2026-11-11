# product-recommendations

> personalised shelf ranking - repository for the e-commerce engagement.

## Features

- A personalised ranking of items per shopper
- Meaning-based similarity instead of keyword matching
- An in-memory cache with expiry in front of the database
- A tabular baseline with preprocessing and grid search
- A typed async HTTP service with auto-generated docs

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/recsys_product.py`
- `src/embeddings_product.py`
- `src/redis_product.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
