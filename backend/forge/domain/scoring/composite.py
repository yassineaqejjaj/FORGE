"""Dimension scores, composite with renormalisation, gates and the readable formula (§7.5).

* criterion value used in the composite = mean of its used sources (rule, metric, AI or human);
* dimension = mean of its criteria weighted by ``criterion_weights`` (default: criterion weight);
* composite = ``100 × Σ w_d·s_d / Σ w_d`` over the **available** dimensions with ``w_d > 0``
  (missing dimensions are listed, robustness is a group dimension and never part of a run composite);
* gates (``dimension``/``criterion``/``error``/``rule``) are applied after: ``fail`` forces 0 and
  flags ``gate_failed``, ``cap`` caps the composite; ``passed = not gate_failed and composite ≥
  pass_threshold``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from forge.domain.enums import (
    DIMENSION_LABELS,
    GROUP_DIMENSIONS,
    SEVERITY_RANK,
    Dimension,
    ErrorSeverity,
    GateAction,
)
from forge.domain.rules.text import fr_number
from forge.domain.types import (
    CompositeResult,
    CriterionScore,
    DimensionScore,
    GateResult,
    GateSpec,
    ScoreConfig,
)

GATE_KINDS = ("dimension", "criterion", "error", "rule")


@dataclass(frozen=True, slots=True)
class ErrorFact:
    """Detected error as seen by ``error`` gates."""

    type: str
    severity: ErrorSeverity


def _label(dimension: str) -> str:
    try:
        return DIMENSION_LABELS[Dimension(dimension)]
    except ValueError:
        return dimension


def _pct(value: float) -> str:
    return f"{fr_number(value * 100, 1)} %"


def criterion_values(
    scores: Sequence[CriterionScore], used: Sequence[bool]
) -> dict[str, tuple[Dimension, float, float]]:
    """``criterion → (dimension, value, weight)`` from the scores used in the composite."""
    buckets: dict[str, list[CriterionScore]] = defaultdict(list)
    for score, flag in zip(scores, used, strict=True):
        if flag:
            buckets[score.criterion_key].append(score)
    result: dict[str, tuple[Dimension, float, float]] = {}
    for key, items in buckets.items():
        value = math.fsum(s.value for s in items) / len(items)
        result[key] = (Dimension(items[0].dimension), value, max(s.weight for s in items))
    return result


def dimension_scores(
    scores: Sequence[CriterionScore], used: Sequence[bool], config: ScoreConfig
) -> tuple[list[DimensionScore], list[str]]:
    """Available dimension scores (effective weights renormalised) and missing dimensions."""
    per_dimension: dict[Dimension, list[tuple[str, float, float]]] = defaultdict(list)
    for key, (dimension, value, weight) in criterion_values(scores, used).items():
        if dimension in GROUP_DIMENSIONS:
            continue
        per_dimension[dimension].append((key, value, weight))
    raw: list[tuple[Dimension, float, float, list[str]]] = []
    for dimension, items in per_dimension.items():
        dim_weight = max(0.0, float(config.dimension_weights.get(dimension.value, 0.0)))
        total = math.fsum(w for _, _, w in items)
        if total <= 0:
            continue
        value = math.fsum(v * w for _, v, w in items) / total
        raw.append((dimension, max(0.0, min(1.0, value)), dim_weight, sorted(k for k, _, _ in items)))
    total_weight = math.fsum(w for _, _, w, _ in raw if w > 0)
    result = [
        DimensionScore(
            dimension=dimension,
            value=value,
            weight=weight,
            effective_weight=(weight / total_weight) if total_weight > 0 and weight > 0 else 0.0,
            criteria=keys,
        )
        for dimension, value, weight, keys in raw
    ]
    order = {d: i for i, d in enumerate(Dimension)}
    result.sort(key=lambda d: order[d.dimension])
    available = {d.dimension.value for d in result if d.weight > 0}
    missing = [
        d.value
        for d in Dimension
        if d not in GROUP_DIMENSIONS
        and float(config.dimension_weights.get(d.value, 0.0)) > 0
        and d.value not in available
    ]
    return result, missing


def _evaluate_gate(
    gate: GateSpec,
    *,
    dimensions: dict[str, float],
    criteria: dict[str, float],
    errors: Sequence[ErrorFact],
    failed_rules: Collection[str],
) -> tuple[bool, str]:
    """``(triggered, detail)`` for one gate."""
    kind = gate.kind
    if kind in ("dimension", "criterion"):
        values = dimensions if kind == "dimension" else criteria
        label = _label(gate.target) if kind == "dimension" else gate.target
        threshold = float(gate.min if gate.min is not None else 0.0)
        if gate.target not in values:
            return False, f"{label} non évalué(e) : garde-fou non applicable"
        value = values[gate.target]
        if value < threshold:
            return True, f"{label} {fr_number(value)} < minimum {fr_number(threshold)}"
        return False, f"{label} {fr_number(value)} ≥ minimum {fr_number(threshold)}"
    if kind == "error":
        try:
            minimum = ErrorSeverity(gate.min_severity or ErrorSeverity.low)
        except ValueError:
            minimum = ErrorSeverity.low
        matching = [
            e
            for e in errors
            if (gate.target in ("*", "") or e.type == gate.target)
            and SEVERITY_RANK[ErrorSeverity(e.severity)] >= SEVERITY_RANK[minimum]
        ]
        target = "toute erreur" if gate.target in ("*", "") else gate.target
        if matching:
            worst = max(matching, key=lambda e: SEVERITY_RANK[ErrorSeverity(e.severity)])
            return (
                True,
                f"{len(matching)} erreur(s) {target} de gravité ≥ {minimum.value} "
                f"(max {worst.severity.value})",
            )
        return False, f"aucune erreur {target} de gravité ≥ {minimum.value}"
    if kind == "rule":
        failed = {r.split("#", 1)[0] for r in failed_rules} | set(failed_rules)
        if gate.target in failed:
            return True, f"règle {gate.target} en échec"
        return False, f"règle {gate.target} respectée ou non évaluée"
    return False, f"type de garde-fou inconnu « {kind} » ignoré"


def compute_composite(
    scores: Sequence[CriterionScore],
    used: Sequence[bool],
    config: ScoreConfig,
    *,
    errors: Iterable[ErrorFact] = (),
    failed_rules: Collection[str] = (),
    forced_zero_reason: str | None = None,
) -> CompositeResult:
    """Composite (0–100) of a run with gates and the French formula explaining it."""
    dims, missing = dimension_scores(scores, used, config)
    weighted = [d for d in dims if d.weight > 0]
    total_weight = math.fsum(d.weight for d in weighted)
    if total_weight > 0:
        raw_value = 100.0 * math.fsum(d.weight * d.value for d in weighted) / total_weight
    else:
        raw_value = 0.0
    raw_value = max(0.0, min(100.0, raw_value))
    if weighted:
        terms = " + ".join(
            f"{_label(d.dimension)} {fr_number(d.value)} × {_pct(d.effective_weight)}" for d in weighted
        )
        formula = f"{terms} = {fr_number(raw_value, 1)}"
    else:
        formula = "Aucune dimension pondérée n'a pu être évaluée : score 0"
    if missing:
        formula += (
            f" ; dimensions non évaluées (poids renormalisés) : {', '.join(_label(m) for m in missing)}"
        )
    dimension_values = {d.dimension.value: d.value for d in dims}
    criterion_map = {k: v for k, (_, v, _) in criterion_values(scores, used).items()}
    error_list = list(errors)
    gate_results: list[GateResult] = []
    value = raw_value
    gate_failed = False
    for gate in config.gates:
        triggered, detail = _evaluate_gate(
            gate,
            dimensions=dimension_values,
            criteria=criterion_map,
            errors=error_list,
            failed_rules=failed_rules,
        )
        action = GateAction(gate.action)
        cap = None
        if action == GateAction.cap:
            cap = max(0.0, min(100.0, float(gate.cap if gate.cap is not None else 100.0)))
        gate_results.append(
            GateResult(gate_id=gate.id, passed=not triggered, action=action, detail=detail, cap=cap)
        )
        if not triggered:
            continue
        if action == GateAction.fail:
            gate_failed = True
            formula += f" ; forcé à 0 par le garde-fou {gate.id} ({detail})"
        elif cap is not None and value > cap:
            value = cap
            formula += f" ; plafonné à {fr_number(cap, 0)} par {gate.id} ({detail})"
        elif cap is not None:
            formula += f" ; garde-fou {gate.id} déclenché ({detail}), plafond {fr_number(cap, 0)} sans effet"
    if gate_failed:
        value = 0.0
    if forced_zero_reason:
        value = 0.0
        formula += f" ; {forced_zero_reason} : score forcé à 0"
    value = round(max(0.0, min(100.0, value)), 4)
    passed = not gate_failed and not forced_zero_reason and bool(weighted) and value >= config.pass_threshold
    verdict = "réussi" if passed else "échoué"
    formula += f" → {fr_number(value, 1)}/100 ({verdict}, seuil {fr_number(config.pass_threshold, 0)})"
    return CompositeResult(
        value=value,
        raw_value=round(raw_value, 4),
        dimensions=dims,
        gates=gate_results,
        gate_failed=gate_failed,
        missing_dimensions=missing,
        formula=formula,
        passed=passed,
    )


def validate_gate(gate: GateSpec, *, known_error_types: Collection[str] = ()) -> list[str]:
    problems: list[str] = []
    if not str(gate.id or "").strip():
        problems.append("identifiant de garde-fou requis")
    if gate.kind not in GATE_KINDS:
        return [*problems, f"type de garde-fou inconnu « {gate.kind} » (attendu : {', '.join(GATE_KINDS)})"]
    try:
        action = GateAction(gate.action)
    except ValueError:
        return [*problems, f"action inconnue « {gate.action} » (fail ou cap)"]
    if gate.kind == "dimension":
        try:
            Dimension(gate.target)
        except ValueError:
            problems.append(f"dimension inconnue « {gate.target} »")
        if gate.target in {d.value for d in GROUP_DIMENSIONS}:
            problems.append("la robustesse n'existe qu'au niveau d'un groupe de runs : garde-fou impossible")
    if gate.kind in ("dimension", "criterion") and (gate.min is None or not 0 <= float(gate.min) <= 1):
        problems.append("« min » doit être compris entre 0 et 1")
    if gate.kind == "criterion" and not gate.target:
        problems.append("critère cible requis")
    if gate.kind == "error":
        if gate.target not in ("*",) and known_error_types and gate.target not in known_error_types:
            problems.append(f"type d'erreur inconnu « {gate.target} »")
        if gate.min_severity is not None:
            try:
                ErrorSeverity(gate.min_severity)
            except ValueError:
                problems.append(f"gravité inconnue « {gate.min_severity} »")
    if gate.kind == "rule" and not gate.target:
        problems.append("règle cible requise")
    if action == GateAction.cap and (gate.cap is None or not 0 <= float(gate.cap) <= 100):
        problems.append("« cap » (0 à 100) requis pour l'action cap")
    return problems
