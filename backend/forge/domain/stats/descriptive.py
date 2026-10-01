"""Descriptive statistics that tolerate empty inputs and non-finite values.

Every helper ignores ``None`` / NaN / ±inf and returns ``None`` when the statistic is undefined
(empty sample, or fewer than two values for a dispersion measure) instead of raising: analytics
must degrade gracefully on partially evaluated benchmarks.
"""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


def as_array(values: Iterable[float | int | None]) -> FloatArray:
    """Finite float array (``None`` / NaN / inf dropped)."""
    arr = np.asarray([v for v in values if v is not None], dtype=np.float64)
    if arr.size == 0:
        return arr
    return arr[np.isfinite(arr)]


def mean(values: Iterable[float | int | None]) -> float | None:
    arr = as_array(values)
    return float(arr.mean()) if arr.size else None


def median(values: Iterable[float | int | None]) -> float | None:
    arr = as_array(values)
    return float(np.median(arr)) if arr.size else None


def std(values: Iterable[float | int | None], *, ddof: int = 1) -> float | None:
    """Standard deviation. Sample (``ddof=1``, unbiased variance) by default; ``None`` if n ≤ ddof."""
    arr = as_array(values)
    if arr.size <= ddof:
        return None
    return float(arr.std(ddof=ddof))


def percentile(values: Iterable[float | int | None], q: float) -> float | None:
    """Percentile ``q`` (0–100) with linear interpolation between order statistics."""
    arr = as_array(values)
    if arr.size == 0:
        return None
    return float(np.percentile(arr, q, method="linear"))


def p95(values: Iterable[float | int | None]) -> float | None:
    return percentile(values, 95.0)


def total(values: Iterable[float | int | None]) -> float | None:
    arr = as_array(values)
    return float(arr.sum()) if arr.size else None


def rate(numerator: int, denominator: int) -> float | None:
    """``numerator / denominator`` or ``None`` when the denominator is 0."""
    return numerator / denominator if denominator > 0 else None


def pooled_std(groups: Iterable[Iterable[float | int | None]]) -> tuple[float | None, int]:
    """Pooled within-group standard deviation and its degrees of freedom.

    ``σ_pooled = sqrt(Σ (n_i − 1)·s_i² / Σ (n_i − 1))`` over the groups with at least two values.
    This is the classical estimate of measurement noise when each group holds repetitions of the
    same experimental condition (same scenario, same agent version). Returns ``(None, 0)`` when no
    group has repetitions.
    """
    sum_sq = 0.0
    dof = 0
    for group in groups:
        arr = as_array(group)
        if arr.size < 2:
            continue
        sum_sq += float(((arr - arr.mean()) ** 2).sum())
        dof += arr.size - 1
    if dof == 0:
        return None, 0
    return float(np.sqrt(sum_sq / dof)), dof
