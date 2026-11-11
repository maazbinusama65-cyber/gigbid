# llm-evaluation-harness

> answer quality scorecards - repository for the ai start-up engagement.

## Features

- Held-out metrics, error slices and calibration checks
- Uses **prompt engineering** (see `src/`)
- Uses **OpenAI API** (see `src/`)
- Uses **Python** (see `src/`)
- Uses **MLflow** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/model_eval_llm.py`
- `src/prompt_eng_llm.py`
- `src/openai_api_llm.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
