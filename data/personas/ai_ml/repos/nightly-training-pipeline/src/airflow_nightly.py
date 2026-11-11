from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime

with DAG('nightly_training_pipeline', start_date=datetime(2024, 1, 1), schedule='@daily', catchup=False) as dag:
    PythonOperator(task_id='check_nightly', python_callable=lambda: None)
