"""Several candidates against one baseline: correct the p-values for the number of comparisons.

Each candidate is tested on the same cases against the same baseline. Testing k candidates and keeping the
best one at α = 0.05 each would accept a false improvement far more than 5 % of the time, so the p-values
are adjusted with Holm-Bonferroni (uniformly more powerful than Bonferroni, still controls the
family-wise error rate). Pure functions, no I/O.
"""

from __future__ import annotations

from collections.abc import Sequence

ALPHA = 0.05


def holm_adjust(p_values: Sequence[float | None]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, in the input order (a missing p-value counts as 1.0)."""
    m = len(p_values)
    values = [1.0 if p is None else min(1.0, max(0.0, float(p))) for p in p_values]
    order = sorted(range(m), key=lambda i: values[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (m - rank) * values[index]))
        adjusted[index] = running
    return adjusted


def significant_after_correction(p_values: Sequence[float | None], alpha: float = ALPHA) -> list[bool]:
    return [p < alpha for p in holm_adjust(p_values)]
