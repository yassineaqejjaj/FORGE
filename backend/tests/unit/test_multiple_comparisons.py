"""Holm-Bonferroni correction for several candidates against one baseline."""

from __future__ import annotations

import pytest

from forge.domain.experiments.multiple import holm_adjust, significant_after_correction


def test_holm_adjusted_values_keep_the_input_order_and_are_monotone():
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm_adjust([0.5]) == [0.5]
    assert holm_adjust([]) == []


def test_missing_and_out_of_range_p_values_never_look_significant():
    assert holm_adjust([None, 0.001]) == pytest.approx([1.0, 0.002])
    assert holm_adjust([2.0, -1.0]) == pytest.approx([1.0, 0.0])


def test_correction_removes_a_borderline_win_among_many_candidates():
    # Alone, 0.03 would pass at α=0.05; among 3 candidates it does not.
    assert significant_after_correction([0.03]) == [True]
    assert significant_after_correction([0.03, 0.2, 0.9]) == [False, False, False]
    assert significant_after_correction([0.001, 0.2, 0.9]) == [True, False, False]
