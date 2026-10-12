"""Model efficiency: recommend a cheaper model only when it is as good, with enough runs."""

from __future__ import annotations

from forge.domain.efficiency import recommend
from forge.domain.monitoring import WindowStats


def stats(n: int, passed: int, cost_per_success: float | None) -> WindowStats:
    return WindowStats(
        n_runs=n,
        n_scored=n,
        n_passed=passed,
        pass_rate=passed / n if n else None,
        cost_per_success=cost_per_success,
    )


def test_a_cheaper_model_as_good_as_the_best_is_recommended():
    recs = recommend({"big": stats(100, 90, 0.50), "small": stats(100, 89, 0.20)})
    assert len(recs) == 1
    r = recs[0]
    assert (r.from_model, r.to_model, r.saving) == ("big", "small", 0.6)
    assert "89%" in r.message and "60%" in r.message


def test_a_measurably_worse_model_is_never_recommended_however_cheap():
    assert recommend({"big": stats(100, 90, 0.50), "small": stats(100, 70, 0.05)}) == []


def test_small_savings_and_noisy_small_samples_are_not_worth_a_switch():
    assert recommend({"big": stats(100, 90, 0.50), "small": stats(100, 90, 0.45)}) == []  # only 10 % cheaper
    assert recommend({"big": stats(10, 9, 0.50), "small": stats(10, 9, 0.10)}) == []  # too few runs
    assert recommend({"big": stats(100, 90, 0.50)}) == []  # nothing to compare with
    assert recommend({"big": stats(100, 90, 0.50), "free": stats(100, 90, None)}) == []  # cost unknown


def test_a_slightly_lower_success_rate_within_the_margin_is_tolerated_but_ranked_by_saving():
    recs = recommend(
        {
            "big": stats(200, 180, 0.60),
            "mid": stats(200, 177, 0.40),
            "small": stats(200, 175, 0.15),
            "bad": stats(200, 120, 0.02),
        }
    )
    assert [r.to_model for r in recs] == ["small", "mid"]  # "bad" is significantly worse and excluded


def test_when_the_best_model_is_also_the_cheapest_the_others_are_dominated():
    recs = recommend(
        {"big": stats(100, 90, 0.50), "small": stats(100, 90, 0.20)}
    )  # same success, 60 % cheaper
    assert [(r.kind, r.from_model, r.to_model, r.saving) for r in recs] == [
        ("dominated", "big", "small", 0.6)
    ]
    assert recommend({"a": stats(100, 90, 0.20), "b": stats(100, 90, 0.20)}) == []  # nothing to gain


def test_the_pareto_front_keeps_only_models_nothing_beats_on_both_success_and_cost():
    from forge.domain.efficiency import pareto_front

    front = pareto_front(
        {
            "big": stats(100, 95, 0.60),  # best success, priciest: on the frontier
            "mid": stats(100, 90, 0.20),  # cheaper, a bit less reliable: on the frontier
            "small": stats(100, 70, 0.05),  # cheapest: on the frontier
            "wasteful": stats(100, 85, 0.50),  # beaten by mid on both: dominated
        }
    )
    assert front == {"big", "mid", "small"}


def test_models_that_cannot_be_compared_are_never_on_the_frontier_and_ties_do_not_dominate():
    from forge.domain.efficiency import pareto_front

    assert pareto_front({"few": stats(5, 5, 0.01), "unknown": stats(100, 90, None)}) == set()
    assert pareto_front({"a": stats(100, 90, 0.20), "b": stats(100, 90, 0.20)}) == {"a", "b"}


def test_best_value_is_the_cheapest_among_the_nearly_best_and_needs_something_to_compare():
    from forge.domain.efficiency import best_value

    assert (
        best_value({"big": stats(100, 95, 0.60), "mid": stats(100, 92, 0.20), "small": stats(100, 60, 0.02)})
        == "mid"
    )
    assert best_value({"big": stats(100, 95, 0.60)}) is None
    assert best_value({"big": stats(100, 95, 0.60), "few": stats(5, 5, 0.01)}) is None
