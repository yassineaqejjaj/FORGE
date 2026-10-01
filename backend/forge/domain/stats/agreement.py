"""Correlation and inter-rater agreement (docs/ARCHITECTURE.md §9.4 — human calibration).

* :func:`pearson` — linear correlation; :func:`spearman` — rank correlation (monotonic agreement,
  robust to a judge that is systematically harsher or more lenient). Both need at least 3 points
  (two points are always perfectly correlated) and a non-constant sample, otherwise ``None``.
* :func:`quadratic_weighted_kappa` — Cohen's kappa with quadratic weights on ordinal ratings
  (``0..n_categories-1``): disagreements are penalised by the squared distance, so a 4-vs-5
  disagreement costs much less than 0-vs-5. It corrects for chance agreement given each rater's
  marginal distribution.
* :func:`agreement_rate` — share of pairs whose normalised scores differ by at most ``tolerance``.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence

import numpy as np
from scipy import stats

MIN_CORRELATION_POINTS = 3
DEFAULT_AGREEMENT_TOLERANCE = 0.2
#: Ordinal scale used for kappa: normalised scores are mapped to 0..5.
KAPPA_LEVELS = 5


def _paired(a: Sequence[float], b: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    x = np.asarray(a, dtype=np.float64)
    y = np.asarray(b, dtype=np.float64)
    mask = np.isfinite(x) & np.isfinite(y)
    return x[mask], y[mask]


def _correlation(a: Sequence[float], b: Sequence[float], method: str) -> float | None:
    x, y = _paired(a, b)
    if x.size < MIN_CORRELATION_POINTS or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value = stats.pearsonr(x, y)[0] if method == "pearson" else stats.spearmanr(x, y)[0]
    value = float(value)
    return value if math.isfinite(value) else None


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    return _correlation(a, b, "pearson")


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    return _correlation(a, b, "spearman")


def to_ordinal(value: float, levels: int = KAPPA_LEVELS) -> int:
    """Map a normalised score (0–1) to an integer rating ``0..levels`` (half-up rounding)."""
    clipped = min(1.0, max(0.0, float(value)))
    return math.floor(clipped * levels + 0.5)


def quadratic_weighted_kappa(a: Sequence[int], b: Sequence[int], *, n_categories: int = 6) -> float | None:
    """Cohen's kappa with quadratic weights for ratings in ``0..n_categories-1``.

    ``κ = 1 − Σ w_ij·O_ij / Σ w_ij·E_ij`` with ``w_ij = (i − j)² / (k − 1)²``, ``O`` the observed
    joint distribution and ``E`` the product of the marginals. When chance disagreement is zero
    (both raters always give the same single rating) the observed disagreement is zero too and
    agreement is perfect: ``1.0`` is returned. ``None`` for empty input.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if not a:
        return None
    k = n_categories
    x = np.clip(np.asarray(a, dtype=np.int64), 0, k - 1)
    y = np.clip(np.asarray(b, dtype=np.int64), 0, k - 1)
    observed = np.zeros((k, k), dtype=np.float64)
    np.add.at(observed, (x, y), 1.0)
    n = observed.sum()
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0)) / n
    grid = np.arange(k, dtype=np.float64)
    weights = (grid[:, None] - grid[None, :]) ** 2 / float((k - 1) ** 2)
    num = float((weights * observed).sum())
    den = float((weights * expected).sum())
    if den <= 0.0:
        return 1.0 if num <= 0.0 else 0.0
    return 1.0 - num / den


def agreement_rate(
    a: Sequence[float], b: Sequence[float], *, tolerance: float = DEFAULT_AGREEMENT_TOLERANCE
) -> float | None:
    x, y = _paired(a, b)
    if x.size == 0:
        return None
    return float((np.abs(x - y) <= tolerance + 1e-9).mean())


def mean_absolute_error(a: Sequence[float], b: Sequence[float]) -> float | None:
    x, y = _paired(a, b)
    if x.size == 0:
        return None
    return float(np.abs(x - y).mean())
