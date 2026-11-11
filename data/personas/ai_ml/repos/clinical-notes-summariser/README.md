# clinical-notes-summariser

> adapter-tuned summary model - repository for the healthcare engagement.

## Features

- Uses **LoRA fine-tuning** (see `src/`)
- Uses **PyTorch** (see `src/`)
- Transformer checkpoints loaded through a model hub
- Held-out metrics, error slices and calibration checks

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

## Layout

- `src/finetuning_clinical.py`
- `src/pytorch_clinical.py`
- `src/huggingface_clinical.py`

## Status

Delivered and handed over; this repository is the frozen client copy.
