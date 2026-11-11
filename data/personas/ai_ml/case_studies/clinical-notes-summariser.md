# Domain Fine-tuned Clinical Notes Summariser

**Client industry:** Healthcare  
**Completed:** 2024-08  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: discharge summaries took clinicians 15 minutes each. They described what they wanted as a fine-tuned small model for discharge notes.

## What I built

I set up a small adapter trained on domain text instead of a full retrain.
I used PyTorch for this part.
I used Hugging Face Transformers for this part.
model evaluation did the heavy lifting here.

## Outcome

Result: ROUGE-L up 12 points over the base model and clinician edit time down to 4 minutes.

## Stack

PyTorch, Hugging Face Transformers, model evaluation

