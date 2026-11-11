# Factory Defect Detection

**Client industry:** Manufacturing  
**Completed:** 2023-01  
**Role:** sole engineer, from first call to hand-over

## The problem

The client had a familiar pain: inspectors missed hairline cracks at the end of long shifts. They described what they wanted as a assembly-line camera inspector.

## What I built

We ended up with pictures of paper or parts analysed automatically.
This is where PyTorch came in.
Under the hood: ONNX Runtime.
I used Docker for this part.

## Outcome

Result: recall of 97% on cracks at 40 ms per part on a CPU-only edge box.

## Stack

PyTorch, ONNX Runtime, Docker

