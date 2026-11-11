# ADR 3: Open-weight models, routed by node, configured in YAML

Status: accepted.

`agent/config.yaml` has `open` (default: Groq-hosted open-weight models for the deployment, Ollama locally) and
`paid` profiles. Cheap frequent nodes use a small model, Writer/Critic the strongest open model. A deterministic
`stub` profile exists so CI and tests need no network. Which models ship is decided by `evals/results`, not by
this file.
