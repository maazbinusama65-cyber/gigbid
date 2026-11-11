# Nightly Training Pipeline

**Client industry:** Online marketplace  
**Completed:** 2023-11  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: models were retrained by hand every few months and drifted. They described what they wanted as a scheduled retraining workflow.

## What I built

Airflow did the heavy lifting here.
A key piece was every training run logged with its parameters and metrics.
This is where Docker came in.
On the engineering side I put in place managed cloud training jobs and hosted endpoints.
This is where Python came in.

## Outcome

Result: weekly automated retrains with a rollback gate; drift incidents fell from monthly to none in a year.

## A snippet

```py
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

with DAG('nightly_training_pipeline', start_date=datetime(2024, 1, 1), schedule='@daily', catchup=False) as dag:
    PythonOperator(task_id='build_nightly', python_callable=lambda: None)
```

