"""Wilcoxon signed-rank test on paired differences (docs/ARCHITECTURE.md §9.3).

The Wilcoxon signed-rank test is non-parametric: it only assumes the differences are independent
across pairs and symmetric around their median under H0. Scores are bounded (0–100) and often
skewed, so it is preferred to a paired t-test.

* zero differences carry no sign information and are dropped (Wilcoxon's original treatment);
* ``scipy`` picks the exact null distribution for small samples without ties and the normal
  approximation (with tie correction) otherwise;
* **n < 2** → ``None`` (no test possible); **all differences zero** → ``p = 1.0`` (no evidence of
  any difference).

Note that with a two-sided test at least 6 non-zero pairs are needed to ever reach ``p < 0.05``
(exact minimum p-value for n = 5 is 0.0625): small experiments are reported as inconclusive.
"""

from __future__ import annotations

import warnings
from collections.abc import Iterable

import numpy as np
from scipy import stats

from forge.domain.stats.descriptive import as_array

#: Differences smaller than this (in absolute value) are treated as ties at zero.
ZERO_TOLERANCE = 1e-9


def wilcoxon_signed_rank(differences: Iterable[float | int | None]) -> float | None:
    """Two-sided p-value of the Wilcoxon signed-rank test on paired differences."""
    diffs = as_array(differences)
    if diffs.size < 2:
        return None
    non_zero = diffs[np.abs(diffs) > ZERO_TOLERANCE]
    if non_zero.size == 0:
        return 1.0
    if non_zero.size == 1:
        # One informative pair: the exact two-sided p-value is 1 (both signs equally likely).
        return 1.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            result = stats.wilcoxon(non_zero, zero_method="wilcox", alternative="two-sided")
        except ValueError:
            return 1.0
    p_value = float(result.pvalue)
    if not np.isfinite(p_value):
        return 1.0
    return min(1.0, max(0.0, p_value))
