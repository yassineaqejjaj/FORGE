"""Statistics: bootstrap, Wilcoxon, descriptive helpers, correlations, weighted kappa."""

from __future__ import annotations

import math
import time

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from scipy import stats as sp_stats

from forge.domain.stats import (
    agreement_rate,
    bootstrap_mean,
    mean,
    mean_absolute_error,
    median,
    p95,
    paired_bootstrap,
    pearson,
    pooled_std,
    quadratic_weighted_kappa,
    rate,
    spearman,
    std,
    to_ordinal,
    total,
    wilcoxon_signed_rank,
)
from forge.domain.stats.formatting import fr_number, fr_p_value, fr_percent, plural

# --- Descriptive ---------------------------------------------------------------------------------


def test_descriptive_ignores_missing_and_non_finite_values() -> None:
    values = [1.0, None, 3.0, float("nan"), float("inf"), 5.0]
    assert mean(values) == 3.0
    assert median(values) == 3.0
    assert std(values) == pytest.approx(2.0)
    assert total(values) == 9.0
    assert p95([float(i) for i in range(1, 101)]) == pytest.approx(95.05)


def test_descriptive_empty_or_too_small() -> None:
    assert mean([]) is None
    assert median([None]) is None
    assert std([1.0]) is None
    assert std([1.0], ddof=0) == 0.0
    assert p95([]) is None
    assert rate(1, 0) is None
    assert rate(1, 4) == 0.25


def test_pooled_std_matches_definition() -> None:
    groups = [[1.0, 3.0], [10.0, 14.0, 12.0], [7.0]]
    sigma, dof = pooled_std(groups)
    expected = math.sqrt((2.0 + 8.0) / 3)  # SS = 2 and 8, dof = 1 + 2
    assert dof == 3
    assert sigma == pytest.approx(expected)
    assert pooled_std([[1.0], [2.0]]) == (None, 0)


# --- Bootstrap -----------------------------------------------------------------------------------


def test_bootstrap_is_deterministic_and_contains_the_mean() -> None:
    rng = np.random.default_rng(1)
    values = list(rng.normal(70, 10, size=60))
    first = bootstrap_mean(values)
    second = bootstrap_mean(values)
    assert first == second
    assert first is not None
    assert first.low < first.estimate < first.high
    assert first.n == 60
    # Normal theory: half-width ≈ 1.96 · σ / √n ≈ 2.5
    assert (first.high - first.low) / 2 == pytest.approx(
        1.96 * np.std(values, ddof=1) / math.sqrt(60), rel=0.15
    )


def test_bootstrap_seed_changes_interval_slightly() -> None:
    values = list(np.random.default_rng(3).normal(0, 1, size=30))
    a = bootstrap_mean(values, seed=1)
    b = bootstrap_mean(values, seed=2)
    assert a is not None and b is not None
    assert a.estimate == b.estimate
    assert a.low != b.low
    assert abs(a.low - b.low) < 0.1


def test_bootstrap_degenerate_inputs() -> None:
    assert bootstrap_mean([]) is None
    single = bootstrap_mean([42.0])
    assert single is not None and (single.low, single.high) == (42.0, 42.0)
    constant = bootstrap_mean([5.0] * 10)
    assert constant is not None and constant.low == constant.high == 5.0 and constant.prob_positive == 1.0
    with pytest.raises(ValueError):
        bootstrap_mean([1.0, 2.0], confidence=1.5)


def test_paired_bootstrap_uses_differences() -> None:
    baseline = [60.0, 70.0, 80.0, 65.0, 75.0, 85.0, 55.0, 90.0]
    candidate = [b + 5 + (i % 3) for i, b in enumerate(baseline)]
    result = paired_bootstrap(baseline, candidate)
    assert result is not None
    assert result.estimate == pytest.approx(np.mean(np.array(candidate) - np.array(baseline)))
    assert 5.0 <= result.low <= result.estimate <= result.high <= 7.0
    assert result.prob_positive == 1.0
    with pytest.raises(ValueError):
        paired_bootstrap([1.0], [1.0, 2.0])


def test_bootstrap_performance_10000_resamples_of_1200_values() -> None:
    values = list(np.random.default_rng(0).uniform(0, 100, size=1200))
    started = time.perf_counter()
    result = bootstrap_mean(values, n_resamples=10_000)
    assert result is not None
    assert time.perf_counter() - started < 2.0


@settings(max_examples=40, deadline=None)
@given(st.lists(st.floats(min_value=0, max_value=100), min_size=1, max_size=40))
def test_bootstrap_interval_brackets_estimate(values: list[float]) -> None:
    result = bootstrap_mean(values, n_resamples=500)
    assert result is not None
    assert result.low - 1e-9 <= result.estimate <= result.high + 1e-9
    assert min(values) - 1e-9 <= result.low and result.high <= max(values) + 1e-9


# --- Wilcoxon ------------------------------------------------------------------------------------


def test_wilcoxon_edge_cases() -> None:
    assert wilcoxon_signed_rank([]) is None
    assert wilcoxon_signed_rank([3.0]) is None
    assert wilcoxon_signed_rank([0.0, 0.0, 0.0]) == 1.0
    assert wilcoxon_signed_rank([0.0, 0.0, 4.0]) == 1.0  # a single informative pair


def test_wilcoxon_matches_scipy_and_detects_shift() -> None:
    diffs = [4.0, 6.5, 3.2, 8.1, 5.5, 7.0, -1.0, 4.4, 6.0, 2.2]
    expected = sp_stats.wilcoxon(diffs).pvalue
    assert wilcoxon_signed_rank(diffs) == pytest.approx(expected)
    assert wilcoxon_signed_rank(diffs) < 0.01
    noisy = [1.0, -1.2, 0.5, -0.4, 0.8, -0.9]
    assert wilcoxon_signed_rank(noisy) > 0.5


def test_wilcoxon_needs_six_pairs_for_significance() -> None:
    assert wilcoxon_signed_rank([5.0] * 5) > 0.05
    assert wilcoxon_signed_rank([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) < 0.05


# --- Correlations & agreement --------------------------------------------------------------------


def test_correlations() -> None:
    a = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert pearson(a, [2 * x for x in a]) == pytest.approx(1.0)
    assert spearman(a, [x**3 for x in a]) == pytest.approx(1.0)
    assert spearman(a, [-x for x in a]) == pytest.approx(-1.0)
    assert pearson([0.1, 0.2], [0.3, 0.4]) is None  # 2 points
    assert pearson(a, [0.5] * 5) is None  # constant
    assert spearman([0.1, float("nan"), 0.3, 0.4], [0.1, 0.9, 0.3, 0.4]) == pytest.approx(1.0)


def test_to_ordinal_half_up() -> None:
    assert [to_ordinal(v) for v in (0.0, 0.09, 0.1, 0.5, 0.7, 1.0, 1.4, -0.2)] == [0, 0, 1, 3, 4, 5, 5, 0]


def _reference_qwk(a: list[int], b: list[int], k: int = 6) -> float:
    observed = np.zeros((k, k))
    for x, y in zip(a, b, strict=True):
        observed[x, y] += 1
    weights = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)])
    expected = np.outer(observed.sum(1), observed.sum(0)) / observed.sum()
    return 1 - (weights * observed).sum() / (weights * expected).sum()


def test_quadratic_weighted_kappa() -> None:
    assert quadratic_weighted_kappa([], []) is None
    assert quadratic_weighted_kappa([3, 3, 3], [3, 3, 3]) == 1.0
    assert quadratic_weighted_kappa([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert quadratic_weighted_kappa([0, 1, 2, 3, 4, 5], [5, 4, 3, 2, 1, 0]) < 0
    a, b = [0, 1, 2, 3, 4, 5, 4, 3], [0, 2, 2, 3, 5, 5, 3, 3]
    assert quadratic_weighted_kappa(a, b) == pytest.approx(_reference_qwk(a, b))
    # Near misses are penalised much less than far misses.
    near = quadratic_weighted_kappa([1, 2, 3, 4, 5, 0], [2, 3, 4, 5, 4, 1])
    far = quadratic_weighted_kappa([1, 2, 3, 4, 5, 0], [5, 0, 0, 1, 0, 5])
    assert near is not None and far is not None and near > 0.5 > far


def test_agreement_rate_and_mae() -> None:
    ai = [0.8, 0.6, 0.2, 0.9]
    human = [0.7, 0.2, 0.4, 0.9]
    assert agreement_rate(ai, human) == 0.75  # |0.4| > 0.2 only for the second pair
    assert mean_absolute_error(ai, human) == pytest.approx((0.1 + 0.4 + 0.2 + 0.0) / 4)
    assert agreement_rate([], []) is None


# --- Formatting ----------------------------------------------------------------------------------


def test_french_formatting() -> None:
    assert fr_number(1234.56, 1) == "1 234,6"
    assert fr_number(2.04, 1, signed=True) == "+2,0"
    assert fr_number(-0.04, 1, signed=True) == "0,0"
    assert fr_number(-3.25, 2) == "−3,25"
    assert fr_number(None) == "—"
    assert fr_percent(0.125, 1) == "12,5 %"
    assert fr_p_value(0.0004) == "p < 0,001"
    assert fr_p_value(0.0312) == "p = 0,031"
    assert plural(1, "scénario") == "1 scénario"
    assert plural(3, "scénario") == "3 scénarios"
