# Low-latency Model Serving

**Client industry:** Ad tech  
**Completed:** 2023-07  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: the scoring endpoint timed out under peak traffic. They described what they wanted as a inference microservice.

## What I built

It relied on a framework-neutral model file loaded by a lean runtime.
It relied on a small Python web API with request validation.
We ended up with containerised builds that run the same on every machine.
On the engineering side I put in place a fast key-value layer for sessions and rate limits.
On the engineering side I put in place managed cloud training jobs and hosted endpoints.

## Outcome

Result: p95 latency from 410 ms to 45 ms at 3x the traffic.

## A snippet

```py
import onnxruntime as ort

sess = ort.InferenceSession('model.onnx', providers=['CPUExecutionProvider'])

def build_low(x):
    return sess.run(None, {sess.get_inputs()[0].name: x})[0]
```

