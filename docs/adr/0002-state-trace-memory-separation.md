# ADR 2: Trace is not graph state, memory is not a log

Status: accepted.

Putting tool output in state bloats checkpoints and tempts promotion of raw data into memory. The trace lives in an
append-only per-run file (PII-masked); memory only receives derived observations that pass a named rule
(`agent/memory/promotion_rules.py`). Consequence: replay uses checkpoints, audit uses the trace.
