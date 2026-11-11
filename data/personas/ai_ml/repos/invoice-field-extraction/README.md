# invoice-field-extraction

> paper bill digitiser - repository for the finance engagement.

## Features

- Pictures of paper or parts analysed automatically
- A neural network trained end to end with custom data loaders
- A typed async HTTP service with auto-generated docs
- Long jobs pushed off the request path into a retrying worker pool
- A reproducible image with a one-command local start

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/computer_vision_invoice.py`
- `src/pytorch_invoice.py`
- `src/fastapi_invoice.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
