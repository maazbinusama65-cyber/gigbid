# ADR 5: Platform rules are data

Status: accepted.

A mid-assignment "policy update" must be absorbable by editing data, not code. Rules live in
`agent/policy_rules.yaml` and are merged with the rules the marketplace publishes (`get_platform_policy`); the
Connects cost comes from the same place. Prompts live one-per-file in `agent/prompts/` with a version header.
