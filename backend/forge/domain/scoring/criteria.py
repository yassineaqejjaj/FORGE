"""Per-criterion scores (docs/ARCHITECTURE.md §7.5) from individual verdicts.

One :class:`CriterionScore` per (criterion, source): ``rule`` (weighted mean of the rules by
``rule.weight``), ``metric``, ``ai`` (multi-judge aggregate, §7.4) and ``human`` (mean of the human
evaluations). AI and human rows are both kept; :func:`composite_usage` decides which ones feed the
composite (human replaces AI on a criterion when ``use_human_scores`` is set). Group dimensions
(robustness) never feed a run composite.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from forge.domain.enums import GROUP_DIMENSIONS, Dimension, EvaluatorKind, ScoreSource
from forge.domain.judges.aggregation import JudgeVerdict, aggregate_verdicts
from forge.domain.rules.text import fr_number
from forge.domain.types import AggregationSpec, CriterionScore, CriterionSpec, EvaluationResult, ScoreConfig

SOURCE_BY_KIND: dict[EvaluatorKind, ScoreSource] = {
    EvaluatorKind.rule: ScoreSource.rule,
    EvaluatorKind.metric: ScoreSource.metric,
    EvaluatorKind.llm_judge: ScoreSource.ai,
    EvaluatorKind.human: ScoreSource.human,
}
SOURCE_ORDER: dict[ScoreSource, int] = {
    ScoreSource.rule: 0,
    ScoreSource.metric: 1,
    ScoreSource.ai: 2,
    ScoreSource.human: 3,
}


@dataclass(frozen=True, slots=True)
class JudgeInfo:
    key: str  # judge key (weights of method=weighted are keyed by judge key)
    weight: float = 1.0


def criterion_weight(key: str, config: ScoreConfig, criteria: Mapping[str, CriterionSpec]) -> float:
    if key in config.criterion_weights:
        return max(0.0, float(config.criterion_weights[key]))
    criterion = criteria.get(key)
    return max(0.0, float(criterion.weight)) if criterion else 1.0


def _clamp(value: float) -> float:
    return 0.0 if math.isnan(value) else max(0.0, min(1.0, value))


def _rule_score(
    items: list[tuple[int, EvaluationResult]], rule_weights: Mapping[str, float]
) -> tuple[float, str, str]:
    if len(items) == 1:
        _, r = items[0]
        return r.normalized, "rule", f"Règle {r.evaluator_key} : {fr_number(r.normalized)}. {r.explanation}"
    weights = [
        max(
            0.0,
            float(rule_weights.get(r.evaluator_key, rule_weights.get(r.evaluator_key.split("#")[0], 1.0))),
        )
        for _, r in items
    ]
    total = math.fsum(weights)
    values = [r.normalized for _, r in items]
    if total <= 0:
        value = math.fsum(values) / len(values)
        detail = "poids tous nuls : moyenne simple"
    else:
        value = math.fsum(w * v for w, v in zip(weights, values, strict=True)) / total
        detail = "moyenne pondérée par le poids des règles"
    parts = " ; ".join(
        f"{r.evaluator_key} {fr_number(r.normalized)} (poids {fr_number(w, 1)})"
        for (_, r), w in zip(items, weights, strict=True)
    )
    return value, f"rules({len(items)})", f"{len(items)} règles ({detail}) : {parts} = {fr_number(value)}."


def score_criteria(
    results: Sequence[EvaluationResult],
    config: ScoreConfig,
    criteria: Mapping[str, CriterionSpec],
    *,
    rule_weights: Mapping[str, float] | None = None,
    judges: Mapping[str, JudgeInfo] | None = None,
    aggregation: AggregationSpec | None = None,
) -> list[CriterionScore]:
    """Aggregate verdicts per (criterion, source). ``evaluation_indexes`` point into ``results``."""
    rule_weights = rule_weights or {}
    judges = judges or {}
    aggregation = aggregation or config.aggregation
    groups: dict[tuple[str, ScoreSource], list[tuple[int, EvaluationResult]]] = defaultdict(list)
    dimensions: dict[str, Dimension] = {}
    for index, result in enumerate(results):
        source = SOURCE_BY_KIND.get(EvaluatorKind(result.evaluator_kind))
        if source is None:
            continue
        groups[(result.criterion_key, source)].append((index, result))
        dimensions.setdefault(result.criterion_key, Dimension(result.dimension))
    scores: list[CriterionScore] = []
    for (key, source), items in groups.items():
        weight = criterion_weight(key, config, criteria)
        indexes = [i for i, _ in items]
        spread: float | None = None
        if source == ScoreSource.rule:
            value, method, explanation = _rule_score(items, rule_weights)
            confidence = 1.0
        elif source == ScoreSource.metric:
            _, r = items[-1]
            value, method, explanation, confidence = r.normalized, "metric", r.explanation, 1.0
            indexes = [items[-1][0]]
        elif source == ScoreSource.ai:
            verdicts = [
                JudgeVerdict(
                    judge_key=judges[r.evaluator_key].key
                    if r.evaluator_key in judges
                    else r.evaluator_key.split("@")[0],
                    value=r.normalized,
                    confidence=r.confidence,
                    weight=judges[r.evaluator_key].weight if r.evaluator_key in judges else 1.0,
                    raw_score=r.raw_score,
                    scale_min=r.scale_min,
                    scale_max=r.scale_max,
                )
                for _, r in items
            ]
            aggregate = aggregate_verdicts(verdicts, aggregation)
            value, method, confidence, spread = (
                aggregate.value,
                aggregate.method,
                aggregate.confidence,
                aggregate.spread,
            )
            explanation = aggregate.explanation
            if len(items) == 1:
                explanation = f"{explanation} {items[0][1].explanation}"
        else:  # human
            values = [r.normalized for _, r in items]
            value = math.fsum(values) / len(values)
            confidence = math.fsum(r.confidence for _, r in items) / len(items)
            spread = max(values) - min(values) if len(values) > 1 else None
            method = "human" if len(items) == 1 else f"human_mean({len(items)})"
            if len(items) == 1:
                explanation = f"Évaluation humaine : {fr_number(value)}. {items[0][1].explanation}"
            else:
                explanation = f"Moyenne de {len(items)} évaluations humaines = {fr_number(value)}."
        scores.append(
            CriterionScore(
                criterion_key=key,
                dimension=dimensions[key],
                value=_clamp(value),
                weight=weight,
                source=source,
                confidence=_clamp(confidence),
                explanation=explanation.strip() or "Score calculé.",
                method=method,
                n_evaluations=len(indexes),
                spread=spread,
                evaluation_indexes=indexes,
            )
        )
    scores.sort(key=lambda s: (s.dimension.value, s.criterion_key, SOURCE_ORDER[s.source]))
    return scores


def composite_usage(scores: Sequence[CriterionScore], config: ScoreConfig) -> list[bool]:
    """``used_in_composite`` of each score: humans replace AI when ``use_human_scores``; group
    dimensions and humans (without the option) are excluded."""
    human_keys = {s.criterion_key for s in scores if s.source == ScoreSource.human}
    usage: list[bool] = []
    for score in scores:
        if Dimension(score.dimension) in GROUP_DIMENSIONS:
            usage.append(False)
        elif score.source == ScoreSource.human:
            usage.append(bool(config.use_human_scores))
        elif score.source == ScoreSource.ai and config.use_human_scores and score.criterion_key in human_keys:
            usage.append(False)
        else:
            usage.append(True)
    return usage
