"""Scoring (docs/ARCHITECTURE.md §7.5): metric normalisation, criterion scores, composite and gates."""

from forge.domain.scoring.composite import (
    ErrorFact,
    compute_composite,
    criterion_values,
    dimension_scores,
    validate_gate,
)
from forge.domain.scoring.criteria import JudgeInfo, composite_usage, criterion_weight, score_criteria
from forge.domain.scoring.normalization import METRIC_CRITERIA, linear_score, metric_results

__all__ = [
    "METRIC_CRITERIA",
    "ErrorFact",
    "JudgeInfo",
    "composite_usage",
    "compute_composite",
    "criterion_values",
    "criterion_weight",
    "dimension_scores",
    "linear_score",
    "metric_results",
    "score_criteria",
    "validate_gate",
]
