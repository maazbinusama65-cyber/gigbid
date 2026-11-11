import mlflow

def run_nightly(params, metrics):
    with mlflow.start_run(run_name='nightly_training_pipeline'):
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
