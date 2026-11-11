# factory-defect-detection

> visual QA for machined parts - repository for the manufacturing engagement.

## Features

- Uses **computer vision** (see `src/`)
- A neural network trained end to end with custom data loaders
- A framework-neutral model file loaded by a lean runtime
- Uses **Docker** (see `src/`)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/computer_vision_factory.py`
- `src/pytorch_factory.py`
- `src/onnx_factory.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
