# Payment Fraud Scoring API

**Client industry:** Fintech  
**Completed:** 2023-04  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: rules-based screening blocked good customers and still let fraud through. They described what they wanted as a transaction risk service.

## What I built

This is where XGBoost came in.
It relied on a tabular baseline with preprocessing and grid search.
On the engineering side I put in place a typed async HTTP service with auto-generated docs.
A key piece was a fast key-value layer for sessions and rate limits.
I used A/B testing for this part.
We ended up with a scorecard that shows where the model fails, not just one number.

## Outcome

Result: caught 34% more fraud at the same false-positive rate; p99 latency 38 ms.

## A snippet

```py
import xgboost as xgb

def build_payment(X, y, pos_weight):
    return xgb.XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.05, scale_pos_weight=pos_weight).fit(X, y)
```

