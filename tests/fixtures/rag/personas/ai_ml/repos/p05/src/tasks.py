from celery import Celery

app = Celery('tasks', broker='redis://localhost:6379/0')

@app.task(bind=True, max_retries=5)
def ingest_file(self, path):
    try:
        upsert_rows(path)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=30)
