"""Explicit promotion rules for long-term memory (R7).

Raw tool output NEVER reaches memory. Edits and outcomes first become *observations* in a staging
namespace (derived patterns + counts only). Memory is written only when a rule below says so.
"""
from __future__ import annotations


def should_promote_style_edit(
    edit_count: int, consistent_pattern: bool, distinct_jobs: int = 1,
    min_edits: int = 3, min_distinct_jobs: int = 2,
) -> bool:
    """Style rule: the same edit pattern must be seen `min_edits` times across at least
    `min_distinct_jobs` different jobs. One-off tweaks and single-job quirks never get in."""
    return consistent_pattern and edit_count >= min_edits and distinct_jobs >= min_distinct_jobs


def should_promote_outcome(
    n_with: int, replies_with: int, n_without: int, replies_without: int,
    min_samples: int = 3, min_delta: float = 0.10,
) -> bool:
    """Outcome rule: a proposal feature is promoted for a job category only if it has enough samples
    on both sides and a reply-rate lift of at least `min_delta`."""
    if n_with < min_samples or n_without < min_samples:
        return False
    return (replies_with / n_with) - (replies_without / n_without) >= min_delta
