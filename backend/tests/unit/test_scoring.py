"""Scoring (docs §7.5): metrics, criterion scores, dimensions, composite, gates, formula + invariants."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from forge.domain.defaults import CRITERIA_BY_KEY
from forge.domain.enums import Dimension, ErrorSeverity, EvaluatorKind, GateAction, ScoreSource
from forge.domain.scoring import (
    ErrorFact,
    JudgeInfo,
    composite_usage,
    compute_composite,
    linear_score,
    metric_results,
    score_criteria,
    validate_gate,
)
from forge.domain.types import (
    AggregationSpec,
    CriterionScore,
    EvaluationResult,
    GateSpec,
    NormalizationSpec,
    ScoreConfig,
)
from tests.unit.test_rules import make_ctx

RUN_DIMENSIONS = [d for d in Dimension if d != Dimension.robustness]


def config(weights: dict[str, float] | None = None, **kwargs) -> ScoreConfig:
    return ScoreConfig(
        config_id="c", key="c", version=1, name="c",
        dimension_weights=weights or {"quality": 0.5, "safety": 0.3, "cost": 0.2}, **kwargs,
    )  # fmt: skip


def verdict(kind: EvaluatorKind, key: str, criterion: str, value: float, **kwargs) -> EvaluationResult:
    dimension = (
        CRITERIA_BY_KEY[criterion].dimension
        if criterion in CRITERIA_BY_KEY
        else Dimension(criterion.split(".")[0])
    )
    scale_max = kwargs.pop("scale_max", 1.0 if kind in (EvaluatorKind.rule, EvaluatorKind.metric) else 5.0)
    return EvaluationResult(
        evaluator_kind=kind, evaluator_key=key, criterion_key=criterion, dimension=dimension,
        raw_score=value * scale_max, scale_min=0, scale_max=scale_max, explanation=f"{key} explique", **kwargs,
    )  # fmt: skip


def cs(
    key: str, value: float, *, weight: float = 1.0, source: ScoreSource = ScoreSource.ai
) -> CriterionScore:
    dimension = Dimension(key.split(".")[0])
    return CriterionScore(
        criterion_key=key, dimension=dimension, value=value, weight=weight, source=source, confidence=1,
        explanation="e", method="m",
    )  # fmt: skip


# --- Metrics ---------------------------------------------------------------------------------------


def test_linear_score() -> None:
    assert linear_score(0.01, 0.05, 0.5) == 1.0
    assert linear_score(0.6, 0.05, 0.5) == 0.0
    assert linear_score(0.275, 0.05, 0.5) == pytest.approx(0.5)
    assert linear_score(1.0, 1.0, 1.0) == 1.0 and linear_score(2.0, 1.0, 1.0) == 0.0


def test_metric_results() -> None:
    ctx = make_ctx("x", cost=0.275, latency_ms=32_500, tokens=(600, 150), max_tokens=1000,
                   config=config(normalization=NormalizationSpec()))  # fmt: skip
    results = {r.criterion_key: r for r in metric_results(ctx)}
    assert results["cost.estimated_cost"].normalized == pytest.approx(0.5)
    assert results["latency.total"].normalized == pytest.approx(0.5)
    assert results["cost.tokens"].normalized == pytest.approx(0.5)  # 750 tokens, 1 at ≤500, 0 at 1000
    assert all(r.evaluator_kind == EvaluatorKind.metric and r.explanation for r in results.values())
    assert {r.criterion_key for r in metric_results(make_ctx("x", cost=None, latency_ms=None))} == set()


# --- Criterion scores ------------------------------------------------------------------------------


def test_rules_weighted_mean_and_sources() -> None:
    results = [
        verdict(EvaluatorKind.rule, "R1", "quality.format", 1.0),
        verdict(EvaluatorKind.rule, "R2", "quality.format", 0.0),
        verdict(EvaluatorKind.llm_judge, "a@v1", "quality.format", 0.6),
    ]
    scores = score_criteria(results, config(), CRITERIA_BY_KEY, rule_weights={"R1": 1, "R2": 3})
    rule = next(s for s in scores if s.source == ScoreSource.rule)
    assert rule.value == pytest.approx(0.25) and rule.evaluation_indexes == [0, 1]
    ai = next(s for s in scores if s.source == ScoreSource.ai)
    assert ai.method == "single_judge" and ai.value == pytest.approx(0.6)


def test_judges_aggregated_with_config_method() -> None:
    results = [
        verdict(EvaluatorKind.llm_judge, "a@v1", "quality.accuracy", 0.2, confidence=1),
        verdict(EvaluatorKind.llm_judge, "b@v2", "quality.accuracy", 0.6, confidence=1),
        verdict(EvaluatorKind.llm_judge, "c@v1", "quality.accuracy", 1.0, confidence=1),
    ]
    cfg = config(aggregation=AggregationSpec(method="weighted", weights={"b": 2}))
    (score,) = score_criteria(
        results,
        cfg,
        CRITERIA_BY_KEY,
        judges={"a@v1": JudgeInfo("a"), "b@v2": JudgeInfo("b"), "c@v1": JudgeInfo("c")},
    )
    assert score.value == pytest.approx((0.2 + 1.2 + 1.0) / 4)
    assert score.spread == pytest.approx(0.8) and score.n_evaluations == 3


def test_human_preference() -> None:
    results = [
        verdict(EvaluatorKind.llm_judge, "a@v1", "quality.accuracy", 0.4),
        verdict(EvaluatorKind.human, "human:u1", "quality.accuracy", 1.0),
    ]
    for use_human, expected in ((False, [True, False]), (True, [False, True])):
        cfg = config(use_human_scores=use_human)
        scores = score_criteria(results, cfg, CRITERIA_BY_KEY)
        assert [s.source for s in scores] == [ScoreSource.ai, ScoreSource.human]
        assert composite_usage(scores, cfg) == expected


def test_robustness_never_in_run_composite() -> None:
    scores = [cs("robustness.stability", 0.1), cs("quality.accuracy", 0.9)]
    cfg = config({"quality": 0.5, "robustness": 0.5})
    used = composite_usage(scores, cfg)
    assert used == [False, True]
    result = compute_composite(scores, used, cfg)
    assert result.raw_value == pytest.approx(90.0) and "robustness" not in result.missing_dimensions


def test_criterion_weights_override() -> None:
    results = [
        verdict(EvaluatorKind.llm_judge, "a@v1", "quality.accuracy", 1.0),
        verdict(EvaluatorKind.llm_judge, "a@v1", "quality.completeness", 0.0),
    ]
    cfg = config({"quality": 1}, criterion_weights={"quality.accuracy": 3})
    scores = score_criteria(results, cfg, CRITERIA_BY_KEY)
    composite = compute_composite(scores, composite_usage(scores, cfg), cfg)
    assert composite.raw_value == pytest.approx(75.0)


# --- Composite & gates -----------------------------------------------------------------------------


def test_composite_renormalises_missing_dimensions_and_formula() -> None:
    scores = [cs("quality.accuracy", 0.8), cs("safety.rules", 1.0)]
    result = compute_composite(scores, [True, True], config())
    assert result.raw_value == pytest.approx(100 * (0.5 * 0.8 + 0.3 * 1.0) / 0.8)
    assert result.missing_dimensions == ["cost"]
    assert "Qualité 0,80 × 62,5 %" in result.formula and "Coût" in result.formula
    assert sum(d.effective_weight for d in result.dimensions) == pytest.approx(1.0)


def test_mixed_sources_averaged_per_criterion() -> None:
    scores = [cs("quality.format", 1.0, source=ScoreSource.rule), cs("quality.format", 0.0)]
    result = compute_composite(scores, [True, True], config({"quality": 1}))
    assert result.raw_value == pytest.approx(50.0)


def test_gates_fail_cap_error_rule_criterion() -> None:
    scores = [cs("quality.accuracy", 0.9), cs("safety.rules", 0.3)]
    gates = [
        GateSpec(
            id="safety-floor", kind="dimension", target="safety", min=0.5, action=GateAction.cap, cap=40
        ),
        GateSpec(id="acc", kind="criterion", target="quality.accuracy", min=0.5),
        GateSpec(id="leak", kind="error", target="DATA_LEAK", min_severity="high"),
        GateSpec(id="must", kind="rule", target="R7"),
    ]
    cfg = config({"quality": 0.5, "safety": 0.5}, gates=gates)
    capped = compute_composite(scores, [True, True], cfg)
    assert (
        capped.value == 40 and not capped.gate_failed and "plafonné à 40 par safety-floor" in capped.formula
    )
    leak = compute_composite(
        scores, [True, True], cfg, errors=[ErrorFact("DATA_LEAK", ErrorSeverity.critical)]
    )
    assert leak.value == 0 and leak.gate_failed and not leak.passed
    low = compute_composite(scores, [True, True], cfg, errors=[ErrorFact("DATA_LEAK", ErrorSeverity.medium)])
    assert not low.gate_failed
    rule = compute_composite(scores, [True, True], cfg, failed_rules={"R7#2"})
    assert rule.gate_failed
    assert [g.passed for g in rule.gates] == [False, True, True, False]


def test_pass_threshold_and_forced_zero() -> None:
    scores = [cs("quality.accuracy", 0.75)]
    cfg = config({"quality": 1}, pass_threshold=70)
    assert compute_composite(scores, [True], cfg).passed
    forced = compute_composite(scores, [True], cfg, forced_zero_reason="exécution en échec")
    assert forced.value == 0 and not forced.passed and forced.raw_value == pytest.approx(75)
    empty = compute_composite([], [], cfg)
    assert empty.value == 0 and not empty.passed and "Aucune dimension" in empty.formula


def test_validate_gate() -> None:
    assert validate_gate(GateSpec(id="g", kind="dimension", target="safety", min=0.5)) == []
    assert validate_gate(GateSpec(id="g", kind="dimension", target="robustness", min=0.5)) != []
    assert validate_gate(GateSpec(id="g", kind="nope", target="x")) != []
    assert validate_gate(GateSpec(id="g", kind="dimension", target="safety", min=2)) != []
    assert validate_gate(GateSpec(id="g", kind="error", target="X"), known_error_types={"DATA_LEAK"}) != []
    assert validate_gate(GateSpec(id="g", kind="error", target="*", action=GateAction.cap)) != []


# --- Invariants (hypothesis) ------------------------------------------------------------------------

score_values = st.floats(min_value=0, max_value=1, allow_nan=False)
weights = st.dictionaries(
    st.sampled_from([d.value for d in Dimension]),
    st.one_of(st.just(0.0), st.floats(min_value=1e-6, max_value=10)),
    min_size=1,
)
criterion_sets = st.dictionaries(st.sampled_from(RUN_DIMENSIONS), score_values, min_size=0, max_size=7)


def _scores(values: dict[Dimension, float]) -> list[CriterionScore]:
    return [cs(f"{d.value}.x", v) for d, v in values.items()]


@settings(max_examples=200)
@given(criterion_sets, weights)
def test_composite_bounded_and_equals_renormalised_mean(
    values: dict[Dimension, float], w: dict[str, float]
) -> None:
    scores = _scores(values)
    result = compute_composite(scores, [True] * len(scores), config(w))
    assert 0.0 <= result.value <= 100.0 and 0.0 <= result.raw_value <= 100.0
    available = {d: v for d, v in values.items() if w.get(d.value, 0) > 0}
    if available:
        total = sum(w[d.value] for d in available)
        expected = 100 * sum(w[d.value] * v for d, v in available.items()) / total
        assert result.raw_value == pytest.approx(expected, abs=1e-3)
        assert (
            min(available.values()) * 100 - 1e-3 <= result.raw_value <= max(available.values()) * 100 + 1e-3
        )
    else:
        assert result.raw_value == 0


@settings(max_examples=200)
@given(criterion_sets, weights, st.floats(min_value=0.1, max_value=50))
def test_weight_scaling_invariance(
    values: dict[Dimension, float], w: dict[str, float], factor: float
) -> None:
    scores = _scores(values)
    base = compute_composite(scores, [True] * len(scores), config(w))
    scaled = compute_composite(scores, [True] * len(scores), config({k: v * factor for k, v in w.items()}))
    assert scaled.raw_value == pytest.approx(base.raw_value, abs=1e-3)


@settings(max_examples=200)
@given(criterion_sets, weights, st.floats(min_value=0, max_value=100), st.floats(min_value=0, max_value=1))
def test_cap_and_fail_gates_monotonic(
    values: dict[Dimension, float], w: dict[str, float], cap: float, minimum: float
) -> None:
    scores = _scores(values)
    used = [True] * len(scores)
    plain = compute_composite(scores, used, config(w))
    capped = compute_composite(
        scores,
        used,
        config(
            w,
            gates=[
                GateSpec(
                    id="c", kind="dimension", target="quality", min=minimum, action=GateAction.cap, cap=cap
                )
            ],
        ),
    )
    failed = compute_composite(
        scores, used, config(w, gates=[GateSpec(id="f", kind="dimension", target="quality", min=minimum)])
    )
    assert capped.value <= plain.value + 1e-9 and capped.value <= max(cap, plain.value) + 1e-9
    assert failed.value <= capped.value + 1e-9 or not failed.gate_failed
    assert (
        failed.value in (0.0, plain.value) and (failed.value == 0.0) == failed.gate_failed
    ) or failed.value == 0.0
    if failed.gate_failed:
        assert not failed.passed
    stricter = compute_composite(
        scores,
        used,
        config(
            w,
            gates=[
                GateSpec(
                    id="c",
                    kind="dimension",
                    target="quality",
                    min=minimum,
                    action=GateAction.cap,
                    cap=cap / 2,
                )
            ],
        ),
    )
    assert stricter.value <= capped.value + 1e-9


@settings(max_examples=100)
@given(st.lists(score_values, min_size=1, max_size=5))
def test_criterion_scores_bounded(values: list[float]) -> None:
    results = [
        verdict(EvaluatorKind.llm_judge, f"j{i}@v1", "quality.accuracy", v) for i, v in enumerate(values)
    ]
    results += [verdict(EvaluatorKind.rule, f"R{i}", "quality.format", v) for i, v in enumerate(values)]
    for score in score_criteria(results, config(), CRITERIA_BY_KEY):
        assert 0 <= score.value <= 1 and 0 <= score.confidence <= 1 and score.explanation
