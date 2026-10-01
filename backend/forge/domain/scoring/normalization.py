"""Metric normalisation (docs/ARCHITECTURE.md §7.5): cost, tokens and latency → 0–1 scores.

Linear: 1 at or below the target, 0 at or above the maximum. Tokens are measured against the agent
budget (``budget.max_tokens``): 1 up to half of the budget, 0 at the budget. A metric whose value is
unknown produces no verdict (its dimension is then renormalised away, never invented).
"""

from __future__ import annotations

from forge.domain.defaults import CRITERIA_BY_KEY
from forge.domain.enums import Dimension, EvaluatorKind
from forge.domain.rules.text import fr_number
from forge.domain.types import EvaluationContext, EvaluationResult, NormalizationSpec

COST_CRITERION = "cost.estimated_cost"
TOKENS_CRITERION = "cost.tokens"
LATENCY_CRITERION = "latency.total"
METRIC_CRITERIA = (COST_CRITERION, TOKENS_CRITERION, LATENCY_CRITERION)
TOKENS_TARGET_RATIO = 0.5


def linear_score(value: float, target: float, maximum: float) -> float:
    """1 if ``value ≤ target``, 0 if ``value ≥ maximum``, linear in between (always within [0, 1])."""
    if value <= target:
        return 1.0
    if maximum <= target or value >= maximum:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (value - target) / (maximum - target)))


def _dimension(key: str) -> Dimension:
    criterion = CRITERIA_BY_KEY.get(key)
    return criterion.dimension if criterion else Dimension(key.split(".", 1)[0])


def _metric(key: str, score: float, explanation: str, raw: dict[str, float | None]) -> EvaluationResult:
    return EvaluationResult(
        evaluator_kind=EvaluatorKind.metric,
        evaluator_key=key,
        criterion_key=key,
        dimension=_dimension(key),
        raw_score=round(score, 6),
        scale_min=0.0,
        scale_max=1.0,
        explanation=explanation,
        confidence=1.0,
        raw_response=raw,
    )


def cost_result(cost: float | None, spec: NormalizationSpec) -> EvaluationResult | None:
    if cost is None:
        return None
    score = linear_score(cost, spec.cost_target, spec.cost_max)
    return _metric(
        COST_CRITERION,
        score,
        f"Coût estimé {fr_number(cost, 4)} : cible ≤ {fr_number(spec.cost_target, 4)} (score 1), "
        f"maximum {fr_number(spec.cost_max, 4)} (score 0) → {fr_number(score)}.",
        {"value": cost, "target": spec.cost_target, "max": spec.cost_max},
    )


def tokens_result(tokens: int, max_tokens: int | None) -> EvaluationResult | None:
    if not max_tokens or max_tokens <= 0 or tokens <= 0:
        return None
    target = max_tokens * TOKENS_TARGET_RATIO
    score = linear_score(float(tokens), target, float(max_tokens))
    return _metric(
        TOKENS_CRITERION,
        score,
        f"{tokens} tokens consommés pour un budget de {max_tokens} : score 1 jusqu'à "
        f"{int(target)} tokens, 0 au budget → {fr_number(score)}.",
        {"value": float(tokens), "target": target, "max": float(max_tokens)},
    )


def latency_result(latency_ms: float | None, spec: NormalizationSpec) -> EvaluationResult | None:
    if latency_ms is None:
        return None
    score = linear_score(latency_ms, spec.latency_target_ms, spec.latency_max_ms)
    return _metric(
        LATENCY_CRITERION,
        score,
        f"Latence totale {int(latency_ms)} ms : cible ≤ {int(spec.latency_target_ms)} ms (score 1), "
        f"maximum {int(spec.latency_max_ms)} ms (score 0) → {fr_number(score)}.",
        {"value": latency_ms, "target": spec.latency_target_ms, "max": spec.latency_max_ms},
    )


def metric_results(ctx: EvaluationContext) -> list[EvaluationResult]:
    """Verdicts of the measured metrics available for this run."""
    spec = ctx.config.normalization
    items = [
        cost_result(ctx.estimated_cost, spec),
        tokens_result(ctx.token_usage.total_tokens, ctx.agent.budget.max_tokens),
        latency_result(ctx.latency_ms, spec),
    ]
    return [item for item in items if item is not None]
