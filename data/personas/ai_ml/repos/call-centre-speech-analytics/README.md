# call-centre-speech-analytics

> agent coaching transcripts - repository for the telecom engagement.

## Features

- Uses **Whisper** (see `src/`)
- Uses **NLP** (see `src/`)
- Long jobs pushed off the request path into a retrying worker pool
- Uses **PostgreSQL** (see `src/`)
- Uses **OpenAI API** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/whisper_call.py`
- `src/nlp_call.py`
- `src/celery_call.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
