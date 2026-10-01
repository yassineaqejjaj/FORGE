"""Seeded, vectorised percentile bootstrap (docs/ARCHITECTURE.md §9.1, §9.3).

Assumptions and choices (documented because conclusions depend on them):

* **Percentile method**: the interval is given by the ``α/2`` and ``1 − α/2`` quantiles of the
  bootstrap distribution of the mean. It needs no distributional assumption, but it is known to
  be slightly anti-conservative for very small samples (n < 10): verdicts additionally require a
  Wilcoxon test (:mod:`forge.domain.stats.significance`) and a minimum number of pairs.
* **Paired bootstrap**: for an experiment the resampling unit is the *pair* (same scenario version
  under baseline and candidate). Resampling the per-pair differences keeps the correlation between
  arms, which is what makes a paired design more powerful than comparing two independent means.
* **Determinism**: a fixed seed (:data:`DEFAULT_SEED`) and ``numpy.random.default_rng`` (PCG64)
  make every interval reproducible; the same inputs always give the same interval.
* **Memory**: resamples are drawn in chunks so that 10 000 resamples of 1 200 values never
  allocate more than a few megabytes at once.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from forge.domain.stats.descriptive import FloatArray, as_array

DEFAULT_RESAMPLES = 10_000
DEFAULT_SEED = 20_250_101
DEFAULT_CONFIDENCE = 0.95
#: Upper bound of drawn indexes per chunk (rows × n).
_CHUNK_ELEMENTS = 1_000_000


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    """Point estimate (sample mean) with its percentile bootstrap interval."""

    estimate: float
    low: float
    high: float
    confidence: float
    n: int
    #: Share of bootstrap means strictly above 0 (≈ probability that the true mean is positive).
    prob_positive: float


def _bootstrap_means(values: FloatArray, n_resamples: int, rng: np.random.Generator) -> FloatArray:
    n = values.size
    means = np.empty(n_resamples, dtype=np.float64)
    rows = max(1, _CHUNK_ELEMENTS // max(1, n))
    start = 0
    while start < n_resamples:
        stop = min(n_resamples, start + rows)
        idx = rng.integers(0, n, size=(stop - start, n))
        means[start:stop] = values[idx].mean(axis=1)
        start = stop
    return means


def bootstrap_mean(
    values: Iterable[float | int | None],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> BootstrapResult | None:
    """Percentile bootstrap interval of the mean of ``values`` (``None`` for an empty sample).

    A single value (or a constant sample) yields a degenerate interval ``[x, x]``: there is no
    observed variability to resample.
    """
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    if n_resamples < 1:
        raise ValueError("n_resamples must be ≥ 1")
    arr = as_array(values)
    n = int(arr.size)
    if n == 0:
        return None
    estimate = float(arr.mean())
    if n == 1 or bool(np.all(arr == arr[0])):
        return BootstrapResult(estimate, estimate, estimate, confidence, n, 1.0 if estimate > 0 else 0.0)
    rng = np.random.default_rng(seed)
    means = _bootstrap_means(arr, n_resamples, rng)
    alpha = (1.0 - confidence) / 2.0
    low, high = np.quantile(means, [alpha, 1.0 - alpha])
    return BootstrapResult(
        estimate=estimate,
        low=float(low),
        high=float(high),
        confidence=confidence,
        n=n,
        prob_positive=float((means > 0).mean()),
    )


def paired_bootstrap(
    baseline: Sequence[float],
    candidate: Sequence[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> BootstrapResult | None:
    """Paired bootstrap interval of ``mean(candidate − baseline)``.

    ``baseline[i]`` and ``candidate[i]`` must measure the same unit (scenario). Pairs where either
    side is missing or non-finite are dropped.
    """
    if len(baseline) != len(candidate):
        raise ValueError("paired samples must have the same length")
    diffs = [
        float(c) - float(b)
        for b, c in zip(baseline, candidate, strict=True)
        if b is not None and c is not None and np.isfinite(b) and np.isfinite(c)
    ]
    return bootstrap_mean(diffs, confidence=confidence, n_resamples=n_resamples, seed=seed)
