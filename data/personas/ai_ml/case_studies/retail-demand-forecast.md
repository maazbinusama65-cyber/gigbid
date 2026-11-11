# Retail Demand Forecasting

**Client industry:** Retail  
**Completed:** 2023-06  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: buyers over-ordered slow lines and ran out of fast ones. They described what they wanted as a stock planning forecasts.

## What I built

On the engineering side I put in place seasonal weekly predictions with holiday effects.
Python did the heavy lifting here.
I set up scripted reshaping of large spreadsheets into tidy tables.
On the engineering side I put in place a nightly DAG that reruns safely when a step fails.
I set up SQL tables with constraints, not loose files.

## Outcome

Result: forecast error (WAPE) improved from 31% to 17% and stock-outs fell 22%.

