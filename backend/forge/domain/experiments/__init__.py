"""Paired experiment comparison, regressions, recommendation and CI gate (docs §9.3)."""

from forge.domain.experiments.comparison import (
    COMPARISON_SCHEMA,
    ExperimentComparison,
    MetricComparison,
    ScenarioChange,
    compare,
    compare_errors,
    compare_metric,
    metric_verdict,
    scenario_change,
)
from forge.domain.experiments.recommendation import (
    CONFIDENCE_LABELS,
    RECOMMENDATION_LABELS,
    GateDecision,
    confidence_level,
    evaluate_gate,
    recommend,
)

__all__ = [
    "COMPARISON_SCHEMA",
    "CONFIDENCE_LABELS",
    "RECOMMENDATION_LABELS",
    "ExperimentComparison",
    "GateDecision",
    "MetricComparison",
    "ScenarioChange",
    "compare",
    "compare_errors",
    "compare_metric",
    "confidence_level",
    "evaluate_gate",
    "metric_verdict",
    "recommend",
    "scenario_change",
]
