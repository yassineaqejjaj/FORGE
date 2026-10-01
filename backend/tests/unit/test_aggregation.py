"""Multi-judge aggregation (docs §7.4): every method, spread, confidence, fallbacks."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from forge.domain.enums import AggregationMethod
from forge.domain.judges.aggregation import JudgeVerdict, aggregate_verdicts, validate_aggregation
from forge.domain.types import AggregationSpec


def verdicts(*values: float, confidence: float = 0.8) -> list[JudgeVerdict]:
    return [
        JudgeVerdict(
            judge_key=f"j{i}", value=v, confidence=confidence, raw_score=v * 5, scale_min=0, scale_max=5
        )
        for i, v in enumerate(values)
    ]


def agg(method: AggregationMethod, *values: float, **spec):
    return aggregate_verdicts(verdicts(*values), AggregationSpec(method=method, **spec))


def test_single_verdict() -> None:
    result = agg(AggregationMethod.median, 0.7)
    assert result.method == "single_judge" and result.value == 0.7 and result.spread == 0


def test_mean_median_min() -> None:
    assert agg(AggregationMethod.mean, 0.2, 0.6, 1.0).value == pytest.approx(0.6)
    assert agg(AggregationMethod.median, 0.2, 0.4, 1.0).value == pytest.approx(0.4)
    assert agg(AggregationMethod.min, 0.2, 0.4, 1.0).value == pytest.approx(0.2)
    assert agg(AggregationMethod.median, 0.2, 0.4, 1.0).method == "median(3)"


def test_spread_and_confidence() -> None:
    result = agg(AggregationMethod.mean, 0.2, 1.0)
    assert result.spread == pytest.approx(0.8)
    assert result.confidence == pytest.approx(0.8 * (1 - 0.4))
    assert "désaccord" in result.explanation


def test_majority_vote_and_tie() -> None:
    majority = agg(AggregationMethod.majority_vote, 0.8, 0.8, 0.2)
    assert majority.value == pytest.approx(0.8)
    tie = agg(AggregationMethod.majority_vote, 0.2, 0.6, 1.0)
    assert tie.value == pytest.approx(0.6)  # no majority → median
    assert "médiane" in tie.explanation


def test_weighted_uses_config_then_judge_weight() -> None:
    items = verdicts(0.0, 1.0)
    items[1].weight = 3.0
    by_judge = aggregate_verdicts(items, AggregationSpec(method=AggregationMethod.weighted))
    assert by_judge.value == pytest.approx(0.75)
    by_config = aggregate_verdicts(
        items, AggregationSpec(method=AggregationMethod.weighted, weights={"j0": 3, "j1": 1})
    )
    assert by_config.value == pytest.approx(0.25)
    zero = aggregate_verdicts(
        items, AggregationSpec(method=AggregationMethod.weighted, weights={"j0": 0, "j1": 0})
    )
    assert zero.value == pytest.approx(0.5) and zero.fallback_reason


def test_custom_expression_and_fallback() -> None:
    result = agg(
        AggregationMethod.custom,
        0.4,
        0.8,
        expression="min(scores) if max(scores) - min(scores) > 0.3 else mean(scores)",
    )
    assert result.value == pytest.approx(0.4) and result.fallback_reason is None
    clamped = agg(AggregationMethod.custom, 0.4, 0.8, expression="sum(scores)")
    assert clamped.value == 1.0 and "borné" in clamped.explanation
    broken = agg(AggregationMethod.custom, 0.4, 0.8, expression="__import__('os')")
    assert broken.value == pytest.approx(0.6) and broken.fallback_reason


def test_validate_aggregation() -> None:
    assert (
        validate_aggregation(AggregationSpec(method=AggregationMethod.custom, expression="mean(scores)"))
        == []
    )
    assert (
        validate_aggregation(AggregationSpec(method=AggregationMethod.custom, expression="os.system")) != []
    )
    assert validate_aggregation(AggregationSpec(method=AggregationMethod.weighted, weights={"j": -1})) != []


def test_empty_verdicts_rejected() -> None:
    with pytest.raises(ValueError):
        aggregate_verdicts([])


@given(
    st.lists(st.floats(min_value=0, max_value=1), min_size=1, max_size=6),
    st.sampled_from(list(AggregationMethod)),
)
def test_aggregate_always_within_bounds(values: list[float], method: AggregationMethod) -> None:
    result = aggregate_verdicts(verdicts(*values), AggregationSpec(method=method, expression="mean(scores)"))
    assert 0.0 <= result.value <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert (
        min(values) - 1e-9 <= result.value <= max(values) + 1e-9 or method == AggregationMethod.majority_vote
    )
