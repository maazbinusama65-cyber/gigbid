# ADR 4: Exactly-once submission is enforced at two layers

Status: accepted.

1. Graph: `submit` is a no-op if state already holds a submission, and the thread id is deterministic
   (`bid:<user>:<job>`), so a restarted worker resumes rather than re-runs.
2. Marketplace MCP: every write requires an idempotency key persisted outside the process, so a retried call after
   a crash returns the first result and never spends Connects twice.
