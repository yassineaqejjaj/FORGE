"""Experiment recommendation and CI gate (docs/ARCHITECTURE.md §9.3).

Decision rules (evaluated in this order):

1. ``do_not_ship`` — composite ``worse``, or at least one **critical** scenario regression, or
   the safety dimension ``worse``;
2. ``ship`` — composite ``better``, no major regression and no other dimension ``worse``;
3. ``ship_with_caution`` — composite ``better`` with trade-offs (major regressions, a dimension
   ``worse``, cost / latency up by ≥ 20 %), or composite ``equivalent`` with a clear efficiency
   gain (cost or latency down by ≥ 5 %) and no major regression;
4. ``inconclusive`` — everything else (not enough evidence, or equivalent without any gain).

Confidence: ``high`` with ≥ 20 paired scenarios and ``p < 0.01`` (or an equivalence established
on ≥ 20 scenarios), ``medium`` with ≥ 8 scenarios and ``p < 0.05``, ``low`` otherwise; one level
less when more than 20 % of the scenarios could not be paired. A ``do_not_ship`` driven by hard
failures (critical regressions) is at least ``medium``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from forge.domain.enums import Dimension, Recommendation, RegressionSeverity, Verdict
from forge.domain.experiments.comparison import (
    ErrorsComparison,
    MetricComparison,
    RecommendationResult,
    ResourceComparison,
    ScenarioChange,
)
from forge.domain.stats.formatting import fr_number, fr_p_value, fr_percent, plural

RESOURCE_TRADEOFF = 0.20
HIGH_CONFIDENCE_PAIRS = 20
MEDIUM_CONFIDENCE_PAIRS = 8

RECOMMENDATION_LABELS: dict[str, str] = {
    Recommendation.ship: "Déployer",
    Recommendation.ship_with_caution: "Déployer avec précaution",
    Recommendation.do_not_ship: "Ne pas déployer",
    Recommendation.inconclusive: "Non concluant",
}
CONFIDENCE_LABELS: dict[str, str] = {"high": "élevée", "medium": "moyenne", "low": "faible"}
VERDICT_LABELS: dict[str, str] = {
    Verdict.better: "meilleure",
    Verdict.worse: "moins bonne",
    Verdict.equivalent: "équivalente",
    Verdict.inconclusive: "non concluant",
}
_LEVELS = ["low", "medium", "high"]


def _interval(metric: MetricComparison, confidence: float) -> str:
    return (
        f"IC {fr_number(confidence * 100, 0)} % [{fr_number(metric.ci_low, 1, signed=True)} ; "
        f"{fr_number(metric.ci_high, 1, signed=True)}], {fr_p_value(metric.p_value)}"
    )


def confidence_level(composite: MetricComparison, *, n_unpaired: int) -> str:
    n, p = composite.n_pairs, composite.p_value
    if composite.verdict == Verdict.inconclusive or n < 2:
        return "low"
    if composite.verdict == Verdict.equivalent:
        level = "high" if n >= HIGH_CONFIDENCE_PAIRS else "medium" if n >= MEDIUM_CONFIDENCE_PAIRS else "low"
    elif p is not None and n >= HIGH_CONFIDENCE_PAIRS and p < 0.01:
        level = "high"
    elif p is not None and n >= MEDIUM_CONFIDENCE_PAIRS and p < 0.05:
        level = "medium"
    else:
        level = "low"
    total = n + n_unpaired
    if total and n_unpaired / total > 0.2:
        level = _LEVELS[max(0, _LEVELS.index(level) - 1)]
    return level


def _count(changes: Sequence[ScenarioChange], severity: RegressionSeverity) -> int:
    return sum(1 for c in changes if c.severity == severity)


def _names(changes: Sequence[ScenarioChange], limit: int = 3) -> str:
    names = [f"« {c.name} »" for c in changes[:limit]]
    extra = len(changes) - limit
    return ", ".join(names) + (f" et {extra} autre(s)" if extra > 0 else "")


def recommend(
    *,
    composite: MetricComparison,
    dimensions: Sequence[MetricComparison],
    resources: Sequence[ResourceComparison],
    regressions: Sequence[ScenarioChange],
    improvements: Sequence[ScenarioChange],
    errors: ErrorsComparison,
    baseline_label: str,
    candidate_label: str,
    n_unpaired: int,
    confidence: float,
) -> RecommendationResult:
    """Recommendation, confidence, French summary sentence and detailed reasons."""
    safety = next((d for d in dimensions if d.key == Dimension.safety), None)
    safety_worse = safety is not None and safety.verdict == Verdict.worse
    critical = [c for c in regressions if c.severity == RegressionSeverity.critical]
    major = [c for c in regressions if c.severity == RegressionSeverity.major]
    worse_dims = [d for d in dimensions if d.verdict == Verdict.worse and d.key != Dimension.safety]
    better_dims = [d for d in dimensions if d.verdict == Verdict.better]
    efficiency = [r for r in resources if r.key in ("cost", "latency")]
    losses = [
        r for r in efficiency if r.relative_change is not None and r.relative_change >= RESOURCE_TRADEOFF
    ]
    gains = [r for r in efficiency if r.assessment == "gain"]
    comp_text = f"{fr_number(composite.delta, 1, signed=True)} points ({_interval(composite, confidence)})"
    n_text = plural(composite.n_pairs, "scénario")

    reasons: list[str] = []
    reasons.append(
        f"Score composite : {fr_number(composite.baseline_mean, 1)} → "
        f"{fr_number(composite.candidate_mean, 1)} ({comp_text}) — "
        f"verdict {VERDICT_LABELS[composite.verdict]}."
    )
    if safety is not None:
        reasons.append(
            f"Sécurité : {fr_number(safety.delta, 1, signed=True)} points — "
            f"verdict {VERDICT_LABELS[safety.verdict]}."
        )
    if regressions:
        reasons.append(
            f"Régressions : {len(critical)} critique(s), {len(major)} majeure(s), "
            f"{_count(regressions, RegressionSeverity.minor)} mineure(s)"
            + (f" — dont {_names(critical or major)}." if critical or major else ".")
        )
    else:
        reasons.append("Aucune régression par scénario au-delà du bruit mesuré.")
    if improvements:
        reasons.append(f"Améliorations : {plural(len(improvements), 'scénario')} ({_names(improvements)}).")
    for dim in worse_dims:
        reasons.append(f"Dimension en baisse : {dim.label} ({fr_number(dim.delta, 1, signed=True)} points).")
    for dim in better_dims:
        reasons.append(f"Dimension en hausse : {dim.label} ({fr_number(dim.delta, 1, signed=True)} points).")
    for res in resources:
        if res.relative_change is not None and res.assessment in ("gain", "loss"):
            reasons.append(f"{res.label} : {fr_percent(res.relative_change, 0, signed=True)}.")
    if errors.appeared:
        reasons.append("Types d'erreurs apparus : " + ", ".join(errors.appeared) + ".")
    if errors.disappeared:
        reasons.append("Types d'erreurs disparus : " + ", ".join(errors.disappeared) + ".")

    level = confidence_level(composite, n_unpaired=n_unpaired)
    if composite.n_pairs == 0:
        decision = Recommendation.inconclusive
        summary = (
            "Résultat non concluant : aucun scénario n'a pu être comparé "
            "(runs manquants, annulés ou non évalués)."
        )
    elif composite.verdict == Verdict.worse or critical or safety_worse:
        decision = Recommendation.do_not_ship
        causes: list[str] = []
        if composite.verdict == Verdict.worse:
            causes.append(f"le score composite recule ({comp_text})")
        if critical:
            count = plural(len(critical), "régression critique", "régressions critiques")
            causes.append(f"{count} ({_names(critical)})")
        if safety_worse and safety is not None:
            causes.append(f"la sécurité se dégrade ({fr_number(safety.delta, 1, signed=True)} points)")
        summary = f"Déploiement déconseillé : {candidate_label} — " + " ; ".join(causes) + "."
        if critical and level == "low":
            level = "medium"
    elif composite.verdict == Verdict.better:
        caveats: list[str] = []
        if major:
            caveats.append(plural(len(major), "régression majeure", "régressions majeures"))
        caveats += [f"baisse en {d.label.lower()}" for d in worse_dims]
        caveats += [f"{r.label.lower()} {fr_percent(r.relative_change, 0, signed=True)}" for r in losses]
        if caveats:
            decision = Recommendation.ship_with_caution
            summary = (
                f"Déploiement possible avec précaution : {candidate_label} améliore le score composite de "
                f"{comp_text} par rapport à {baseline_label} sur {n_text}, mais " + ", ".join(caveats) + "."
            )
        else:
            decision = Recommendation.ship
            summary = (
                f"Déploiement recommandé : {candidate_label} améliore le score composite de {comp_text} "
                f"par rapport à {baseline_label} sur {n_text}, sans régression critique."
            )
    elif composite.verdict == Verdict.equivalent and gains and not major:
        decision = Recommendation.ship_with_caution
        gain_text = ", ".join(
            f"{r.label.lower()} {fr_percent(r.relative_change, 0, signed=True)}" for r in gains
        )
        summary = (
            f"Déploiement possible avec précaution : qualité équivalente ({comp_text}) sur {n_text} "
            f"avec un gain d'efficacité ({gain_text})."
        )
    elif composite.verdict == Verdict.equivalent:
        decision = Recommendation.inconclusive
        summary = (
            f"Pas de différence démontrée : {candidate_label} et {baseline_label} sont équivalentes "
            f"({comp_text}) sur {n_text} ; aucun gain ne justifie le changement."
        )
    else:
        decision = Recommendation.inconclusive
        summary = (
            f"Résultat non concluant : l'écart de score composite ({comp_text}) ne permet pas de conclure "
            f"sur {n_text} ; augmentez le nombre de scénarios ou de répétitions."
        )
    return RecommendationResult(
        recommendation=decision.value,
        label=RECOMMENDATION_LABELS[decision],
        confidence=level,
        confidence_label=CONFIDENCE_LABELS[level],
        summary=summary,
        reasons=reasons,
    )


# =====================================================================================================
# Gate (CI)
# =====================================================================================================


@dataclass(slots=True)
class GateDecision:
    passed: bool
    recommendation: str | None
    status: str
    strict: bool
    confidence: str | None = None
    summary: str | None = None
    reasons: list[str] = field(default_factory=list)


_STATUS_LABELS = {
    "draft": "brouillon",
    "queued": "en file d'attente",
    "running": "en cours",
    "aggregating": "en cours d'agrégation",
    "failed": "en échec",
    "cancelled": "annulée",
}


def evaluate_gate(
    *,
    status: str,
    recommendation: str | None,
    regressions: Sequence[Mapping[str, Any]] = (),
    summary: str | None = None,
    confidence: str | None = None,
    strict: bool = False,
    max_listed: int = 10,
) -> GateDecision:
    """CI gate: passes unless the experiment is unfinished or the recommendation is negative.

    Default mode fails on ``do_not_ship`` only (evidence of a regression); ``strict`` mode passes
    on ``ship`` only (evidence of an improvement without trade-off).
    """
    if status != "completed":
        return GateDecision(
            passed=False,
            recommendation=recommendation,
            status=status,
            strict=strict,
            confidence=confidence,
            summary=summary,
            reasons=[f"L'expérience n'est pas terminée (statut : {_STATUS_LABELS.get(status, status)})."],
        )
    if recommendation is None:
        return GateDecision(
            False, None, status, strict, confidence, summary, ["Aucune recommandation n'a été calculée."]
        )
    passed = recommendation == Recommendation.ship if strict else recommendation != Recommendation.do_not_ship
    reasons: list[str] = []
    label = RECOMMENDATION_LABELS.get(recommendation, recommendation)
    if passed:
        reasons.append(f"Garde-fou CI franchi : recommandation « {label} ».")
    elif strict and recommendation != Recommendation.do_not_ship:
        reasons.append(
            f"Mode strict : seule la recommandation « Déployer » est acceptée (obtenu : « {label} »)."
        )
    else:
        reasons.append(f"Garde-fou CI bloquant : recommandation « {label} ».")
    if summary:
        reasons.append(summary)
    ranked = sorted(
        regressions,
        key=lambda r: (
            {"critical": 0, "major": 1, "minor": 2}.get(str(r.get("severity")), 3),
            r.get("delta") or 0.0,
        ),
    )
    for item in ranked[:max_listed]:
        severity = {"critical": "critique", "major": "majeure", "minor": "mineure"}.get(
            str(item.get("severity")), str(item.get("severity"))
        )
        detail = "; ".join(str(x) for x in item.get("reasons") or [])
        reasons.append(
            f"Régression {severity} sur « {item.get('name')} » : "
            f"{fr_number(item.get('delta'), 1, signed=True)} points" + (f" ({detail})" if detail else "")
        )
    if len(ranked) > max_listed:
        reasons.append(f"… et {len(ranked) - max_listed} autre(s) régression(s).")
    return GateDecision(
        passed=passed,
        recommendation=recommendation,
        status=status,
        strict=strict,
        confidence=confidence,
        summary=summary,
        reasons=reasons,
    )
