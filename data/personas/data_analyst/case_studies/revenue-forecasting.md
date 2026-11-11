# Revenue Forecasting

**Client industry:** SaaS  
**Completed:** 2023-11  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: budget forecasts were a flat growth rate. They described what they wanted as a next-quarter projections.

## What I built

We ended up with next-quarter numbers with seasonality and prediction ranges.
I used Python for this part.
On the engineering side I put in place careful inference instead of eyeballing charts.
On the engineering side I put in place advanced spreadsheet models with lookups and pivot tables.

## Outcome

Result: MAPE of 6% over four quarters versus 15% for the old method.

## Stack

Python

## A snippet

```py
from statsmodels.tsa.holtwinters import ExponentialSmoothing

def handle_revenue(series, horizon=13):
    fit = ExponentialSmoothing(series, trend='add', seasonal='add', seasonal_periods=52).fit()
    return fit.forecast(horizon)
```

