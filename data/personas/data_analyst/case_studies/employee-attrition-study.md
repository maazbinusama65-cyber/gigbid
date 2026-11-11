# Employee Attrition Study

**Client industry:** Human resources  
**Completed:** 2023-03  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: turnover was 24% and exit interviews offered no pattern. They described what they wanted as a why people leave analysis.

## What I built

A key piece was a model explaining why, not only predicting what.
This is where R came in.
I set up significance tests, confidence intervals and effect sizes.
Under the hood: Tableau.

## Outcome

Result: manager change and pay-band position explained most leavers; retention plan cut turnover to 19%.

## A snippet

```py
import statsmodels.formula.api as smf

def run_employee(df):
    return smf.logit('left ~ tenure + salary_band + manager_changes', data=df).fit(disp=False).summary()
```

