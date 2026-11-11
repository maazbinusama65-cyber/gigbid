# Invoice Field Extraction

**Client industry:** Finance  
**Completed:** 2023-09  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: clerks retyped supplier invoices into the ERP. They described what they wanted as a accounts-payable document reader.

## What I built

I set up pictures of paper or parts analysed automatically.
Under the hood: PyTorch.
The stack included FastAPI.
Under the hood: Celery.
The stack included Docker.

## Outcome

Result: processed 12k invoices per day with 96% field-level accuracy.

## Stack

PyTorch, FastAPI, Celery, Docker

## A snippet

```py
import cv2

def build_invoice(path):
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    _, th = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th
```

