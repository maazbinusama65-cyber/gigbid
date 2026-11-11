from celery import Celery

app = Celery('call_centre_speech_analytics', broker='redis://localhost:6379/0')

@app.task(bind=True, max_retries=3, default_retry_delay=30)
def handle_call(self, payload):
    try:
        return {'ok': True, 'n': len(payload)}
    except Exception as exc:
        raise self.retry(exc=exc)
