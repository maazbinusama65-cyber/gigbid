# Subscription Churn Prediction

**Client industry:** Subscription media  
**Completed:** 2022-11  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: the retention team contacted customers at random. They described what they wanted as a retention risk scoring.

## What I built

scikit-learn did the heavy lifting here.
XGBoost did the heavy lifting here.
We ended up with tabular wrangling in dataframes with merges and group-bys.
This is where MLflow came in.
I set up split tests read out with confidence intervals.

## Outcome

Result: top-decile precision of 44% and 9% lower monthly churn in a holdout test.

## Stack

scikit-learn, XGBoost, MLflow

## A snippet

```py
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression

def check_churn():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, class_weight='balanced'))
```

