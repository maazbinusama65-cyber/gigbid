# ADR 1: Fit Matcher extracts requirements itself

Status: accepted.

The assignment runs Job Analyst, Risk Assessor and Fit Matcher in parallel, but the Matcher needs requirements.
Options: (a) serialise Analyst -> Matcher, (b) a shared deterministic extractor. Chose (b): it keeps the parallel
topology required by R3 and removes an LLM call from the critical path. Cost: the Matcher's requirement list can
differ slightly from the Analyst's richer one; the decision node reads the Matcher's.
