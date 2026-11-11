# Call Centre Speech Analytics

**Client industry:** Telecom  
**Completed:** 2024-04  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: supervisors could review under 1% of recorded calls. They described what they wanted as a voice call summariser.

## What I built

A key piece was automatic speech-to-text on recorded phone calls.
I set up language processing over thousands of short documents.
The stack included Celery.
On the engineering side I put in place a relational store with proper indexes and migrations.
I set up hosted large-language-model calls with retries and cost caps.

## Outcome

Result: every call transcribed and summarised overnight; QA coverage went from 1% to 100%.

## Stack

Celery

## A snippet

```py
import whisper

model = whisper.load_model('small')

def run_call(path):
    out = model.transcribe(path, word_timestamps=False)
    return out['text'], out['segments']
```

