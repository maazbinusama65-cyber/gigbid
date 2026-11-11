# LLM Evaluation Harness

**Client industry:** AI start-up  
**Completed:** 2024-09  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: prompt changes shipped without anyone knowing if answers got worse. They described what they wanted as a regression tests for prompts.

## What I built

model evaluation did the heavy lifting here.
I used prompt engineering for this part.
A key piece was hosted large-language-model calls with retries and cost caps.
I set up a set of small automation tools.
MLflow did the heavy lifting here.

## Outcome

Result: 300-case suite in CI; blocked 5 regressions before release.

## Stack

model evaluation, prompt engineering, MLflow

