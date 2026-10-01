"""Multi-judge aggregation per criterion (docs/ARCHITECTURE.md §7.4).

Verdicts are normalised to 0–1 before aggregation. ``spread = max − min`` measures disagreement;
aggregated confidence = mean(confidences) × (1 − spread / 2). Individual verdicts are never
discarded: the caller keeps them and references them from the ``scores`` row.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from forge.domain.enums import AggregationMethod
from forge.domain.judges.safe_expr import ExpressionError, compile_expression
from forge.domain.rules.text import fr_number
from forge.domain.types import AggregationSpec

METHOD_LABELS: dict[AggregationMethod, str] = {
    AggregationMethod.mean: "Moyenne",
    AggregationMethod.median: "Médiane",
    AggregationMethod.majority_vote: "Vote majoritaire",
    AggregationMethod.weighted: "Moyenne pondérée",
    AggregationMethod.min: "Minimum (le plus sévère)",
    AggregationMethod.custom: "Expression personnalisée",
}


@dataclass(slots=True)
class JudgeVerdict:
    """One judge's normalised verdict on one criterion."""

    judge_key: str
    value: float  # 0–1
    confidence: float = 1.0
    weight: float = 1.0  # JudgeSpec.weight (default for method=weighted)
    raw_score: float | None = None
    scale_min: float = 0.0
    scale_max: float = 5.0


@dataclass(slots=True)
class AggregateResult:
    value: float
    confidence: float
    spread: float
    method: str  # "median(3)", "single_judge", "custom(2)"…
    explanation: str
    fallback_reason: str | None = None


def _clamp01(value: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(0.0, min(1.0, value))


def _values_text(verdicts: Sequence[JudgeVerdict]) -> str:
    return " ; ".join(f"{v.judge_key} {fr_number(v.value)}" for v in verdicts)


def _majority(verdicts: Sequence[JudgeVerdict]) -> tuple[float, str]:
    rounded: list[float] = []
    for v in verdicts:
        if v.raw_score is not None and v.scale_max > v.scale_min:
            note = round(v.raw_score)
            rounded.append(_clamp01((note - v.scale_min) / (v.scale_max - v.scale_min)))
        else:
            rounded.append(round(v.value * 5) / 5)
    counts = Counter(round(r, 6) for r in rounded)
    best = max(counts.values())
    winners = [value for value, count in counts.items() if count == best]
    if len(winners) == 1 and best > 1:
        return winners[0], f"note arrondie la plus fréquente ({best}/{len(verdicts)} juges)"
    return float(statistics.median(v.value for v in verdicts)), "égalité des votes : médiane retenue"


def aggregate_verdicts(
    verdicts: Sequence[JudgeVerdict], spec: AggregationSpec | None = None
) -> AggregateResult:
    """Aggregate normalised verdicts according to ``spec`` (default: mean)."""
    if not verdicts:
        raise ValueError("aggregate_verdicts() requires at least one verdict")
    spec = spec or AggregationSpec()
    values = [_clamp01(v.value) for v in verdicts]
    confidences = [_clamp01(v.confidence) for v in verdicts]
    spread = max(values) - min(values)
    confidence = _clamp01((math.fsum(confidences) / len(confidences)) * (1 - spread / 2))
    if len(verdicts) == 1:
        v = verdicts[0]
        return AggregateResult(
            value=values[0],
            confidence=confidences[0],
            spread=0.0,
            method="single_judge",
            explanation=f"Verdict unique du juge {v.judge_key} : {fr_number(values[0])}.",
        )
    method = AggregationMethod(spec.method)
    n = len(verdicts)
    detail = ""
    fallback: str | None = None
    if method == AggregationMethod.mean:
        value = math.fsum(values) / n
    elif method == AggregationMethod.median:
        value = float(statistics.median(values))
    elif method == AggregationMethod.min:
        value = min(values)
    elif method == AggregationMethod.majority_vote:
        value, detail = _majority(verdicts)
    elif method == AggregationMethod.weighted:
        weights = [max(0.0, float(spec.weights.get(v.judge_key, v.weight))) for v in verdicts]
        total = math.fsum(weights)
        if total <= 0:
            value = math.fsum(values) / n
            fallback = "poids tous nuls : moyenne simple utilisée"
        else:
            value = math.fsum(w * x for w, x in zip(weights, values, strict=True)) / total
            detail = "poids " + ", ".join(
                f"{v.judge_key}={fr_number(w)}" for v, w in zip(verdicts, weights, strict=True)
            )
    else:  # custom
        weights = [max(0.0, float(spec.weights.get(v.judge_key, v.weight))) for v in verdicts]
        try:
            compiled = compile_expression(spec.expression or "")
            result = compiled.evaluate({"scores": values, "weights": weights, "confidences": confidences})
            if isinstance(result, list | tuple):
                raise ExpressionError("l'expression doit produire un nombre, pas une liste")
            number = float(result)
            if math.isnan(number) or math.isinf(number):
                raise ExpressionError("résultat non numérique")
            value = _clamp01(number)
            detail = f"« {spec.expression} » = {fr_number(number, 3)}"
            if number != value:
                detail += " (borné à [0 ; 1])"
        except (ExpressionError, TypeError, ValueError) as exc:
            value = math.fsum(values) / n
            fallback = f"expression invalide ({exc}) : moyenne simple utilisée"
    value = _clamp01(value)
    label = METHOD_LABELS[method]
    explanation = f"{label} de {n} juges ({_values_text(verdicts)}) = {fr_number(value)}"
    if detail:
        explanation += f" — {detail}"
    explanation += f" ; désaccord (écart max − min) {fr_number(spread)}."
    if fallback:
        explanation += f" Attention : {fallback}."
    return AggregateResult(
        value=value,
        confidence=confidence,
        spread=spread,
        method=f"{method.value}({n})",
        explanation=explanation,
        fallback_reason=fallback,
    )


def validate_aggregation(spec: AggregationSpec) -> list[str]:
    """French validation messages for an aggregation specification."""
    problems: list[str] = []
    try:
        method = AggregationMethod(spec.method)
    except ValueError:
        return [f"méthode d'agrégation inconnue « {spec.method} »"]
    for key, weight in (spec.weights or {}).items():
        try:
            if float(weight) < 0:
                problems.append(f"poids négatif pour le juge « {key} »")
        except (TypeError, ValueError):
            problems.append(f"poids invalide pour le juge « {key} »")
    if method == AggregationMethod.custom:
        try:
            compile_expression(spec.expression or "")
        except ExpressionError as exc:
            problems.append(f"expression personnalisée invalide : {exc}")
    return problems
