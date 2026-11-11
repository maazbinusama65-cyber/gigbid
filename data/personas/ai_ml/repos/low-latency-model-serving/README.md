# low-latency-model-serving

> prediction endpoint hardening - repository for the ad tech engagement.

## Features

- An exported model served on CPU in milliseconds
- Uses **FastAPI** (see `src/`)
- A reproducible image with a one-command local start
- Uses **Redis** (see `src/`)
- A cloud-managed model endpoint behind autoscaling

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/onnx_low.py`
- `src/fastapi_low.py`
- `src/Dockerfile`

## Status

Delivered and handed over; this repository is the frozen client copy.
