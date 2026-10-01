"""Deterministic ``FeedbackReport`` construction (docs/ARCHITECTURE.md §7.7).

* ``strengths`` = criteria ≥ 0.8, ``weaknesses`` = criteria < 0.6 (sorted by score);
* ``errors`` grouped by type: count, maximum severity, examples, evidence;
* ``recommendations`` by deterministic mapping rules (error type / weak criterion / cost / latency →
  :class:`RecommendationCategory`), one per category, priority from the severity of their triggers;
* ``priority_actions`` = titles of the most urgent recommendations.

The same builder serves a single run and a set of runs (:func:`build_group_feedback`); the output
is plain data (``to_dict``) consumed by the UI and by NOVA to draft a candidate agent version.
Evidence never invents anything: it is copied from the detected errors.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from forge.domain.enums import (
    DIMENSION_LABELS,
    SEVERITY_RANK,
    BuiltinErrorType,
    Dimension,
    ErrorSeverity,
    Priority,
    RecommendationCategory,
)
from forge.domain.rules.text import fr_number, one_line
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.domain.types import EvidenceRef, FeedbackRecommendation, FeedbackReportData, to_dict

STRENGTH_MIN = 0.8
WEAKNESS_MAX = 0.6
METRIC_ALERT_MAX = 0.5
MAX_EXAMPLES = 3
MAX_EVIDENCE = 3
MAX_PRIORITY_ACTIONS = 5
DETERMINISTIC = "deterministic"

PRIORITY_RANK: dict[Priority, int] = {Priority.p0: 0, Priority.p1: 1, Priority.p2: 2}


@dataclass(slots=True)
class FeedbackCriterion:
    key: str
    value: float  # 0–1
    name: str = ""
    dimension: Dimension | None = None


@dataclass(slots=True)
class FeedbackError:
    type: str
    severity: ErrorSeverity
    description: str
    evidence: list[EvidenceRef] = field(default_factory=list)
    criterion_key: str | None = None
    run_id: str | None = None


@dataclass(slots=True)
class FeedbackInput:
    score: float | None  # composite 0–100
    passed: bool | None = None
    criteria: list[FeedbackCriterion] = field(default_factory=list)
    errors: list[FeedbackError] = field(default_factory=list)
    gate_failures: list[str] = field(default_factory=list)
    run_failed: str | None = None
    #: Normalised metric scores (``cost.estimated_cost``, ``latency.total``…) when known.
    cost: float | None = None
    latency_ms: float | None = None
    n_runs: int = 1
    #: Labels of custom error types (built-in ones are known).
    error_labels: Mapping[str, str] = field(default_factory=dict)
    label: str = ""


@dataclass(frozen=True, slots=True)
class _RuleText:
    category: RecommendationCategory
    title: str
    description: str


#: Error type → recommendation (docs §7.7 mapping rules).
ERROR_RECOMMENDATIONS: dict[str, _RuleText] = {
    BuiltinErrorType.HALLUCINATION: _RuleText(
        RecommendationCategory.retrieval,
        "Ancrer les réponses dans les sources",
        "Améliorer la récupération des documents pertinents et exiger que chaque affirmation soit étayée par "
        "une source du contexte ; demander à l'agent de signaler l'absence d'information "
        "plutôt que d'inventer.",
    ),
    BuiltinErrorType.SOURCE_ERROR: _RuleText(
        RecommendationCategory.retrieval,
        "Fiabiliser la récupération et la citation des sources",
        "Vérifier que les documents nécessaires sont récupérés et imposer un format de citation qui renvoie "
        "aux identifiants des documents du contexte.",
    ),
    BuiltinErrorType.INSTRUCTION_FAILURE: _RuleText(
        RecommendationCategory.system_prompt,
        "Renforcer les consignes du prompt système",
        "Rendre les contraintes explicites et prioritaires dans le prompt système (liste à vérifier avant "
        "de répondre) et ajouter un exemple de réponse conforme.",
    ),
    BuiltinErrorType.CONTRADICTION: _RuleText(
        RecommendationCategory.system_prompt,
        "Éliminer les contradictions",
        "Demander une relecture de cohérence avant la réponse finale et rappeler de ne pas contredire le "
        "contexte fourni.",
    ),
    BuiltinErrorType.BAD_REASONING: _RuleText(
        RecommendationCategory.system_prompt,
        "Structurer le raisonnement",
        "Guider l'agent vers un raisonnement par étapes justifiées (hypothèses, options, choix motivé) dans "
        "le prompt système.",
    ),
    BuiltinErrorType.MISSING_INFORMATION: _RuleText(
        RecommendationCategory.context,
        "Compléter le contexte et la couverture de la réponse",
        "Fournir à l'agent les informations manquantes (contexte, mémoire projet) et lister dans les "
        "consignes les éléments attendus dans la réponse.",
    ),
    BuiltinErrorType.WRONG_TOOL: _RuleText(
        RecommendationCategory.tools,
        "Clarifier l'usage des outils",
        "Préciser la description et les paramètres des outils, indiquer quand les utiliser (ou non) et "
        "limiter le jeu d'outils à ceux nécessaires.",
    ),
    BuiltinErrorType.TOOL_FAILURE: _RuleText(
        RecommendationCategory.tools,
        "Gérer les échecs d'outils",
        "Valider les paramètres avant appel, exploiter les messages d'erreur et prévoir une stratégie de "
        "repli lorsqu'un outil échoue.",
    ),
    BuiltinErrorType.FORMAT_ERROR: _RuleText(
        RecommendationCategory.output_format,
        "Fiabiliser le format de sortie",
        "Imposer le format attendu (schéma JSON, sections, longueur) via des sorties structurées ou un "
        "gabarit explicite, et valider la sortie avant de la renvoyer.",
    ),
    BuiltinErrorType.MEMORY_ERROR: _RuleText(
        RecommendationCategory.memory,
        "Mettre à jour la mémoire de l'agent",
        "Invalider les informations obsolètes, horodater les faits mémorisés et privilégier "
        "les plus récents.",
    ),
    BuiltinErrorType.POLICY_VIOLATION: _RuleText(
        RecommendationCategory.rule,
        "Ajouter des garde-fous de conformité",
        "Expliciter les règles métier et de conformité, et ajouter un contrôle automatique (règle FORGE ou "
        "filtre de sortie) sur les comportements interdits.",
    ),
    BuiltinErrorType.DATA_LEAK: _RuleText(
        RecommendationCategory.rule,
        "Empêcher la fuite de données sensibles",
        "Masquer les données personnelles du contexte transmis à l'agent, interdire leur reproduction et "
        "ajouter un filtre de sortie (règle no_pii).",
    ),
    BuiltinErrorType.CONTAMINATION: _RuleText(
        RecommendationCategory.context,
        "Isoler les scénarios privés",
        "Le contenu d'un scénario privé a été vu par l'agent : retirer ces données des prompts, "
        "de la mémoire et des jeux d'entraînement, puis renouveler les scénarios concernés.",
    ),
    BuiltinErrorType.EXECUTION_ERROR: _RuleText(
        RecommendationCategory.orchestration,
        "Fiabiliser l'exécution de l'agent",
        "Corriger les erreurs d'appel (point d'accès, authentification, format de réponse) et ajouter des "
        "reprises sur erreur transitoire.",
    ),
    BuiltinErrorType.TIMEOUT: _RuleText(
        RecommendationCategory.orchestration,
        "Réduire le temps d'exécution",
        "Limiter le nombre d'étapes, paralléliser les appels indépendants et fixer des délais par outil.",
    ),
    BuiltinErrorType.BUDGET_EXCEEDED: _RuleText(
        RecommendationCategory.model,
        "Maîtriser la consommation",
        "Réduire le contexte transmis, limiter les tours de boucle ou choisir un modèle moins coûteux pour "
        "les étapes simples.",
    ),
}

#: Weak criterion → recommendation category (when no error explains the weakness).
CRITERION_CATEGORIES: dict[str, RecommendationCategory] = {
    "quality.accuracy": RecommendationCategory.retrieval,
    "quality.completeness": RecommendationCategory.system_prompt,
    "quality.usefulness": RecommendationCategory.system_prompt,
    "quality.format": RecommendationCategory.output_format,
    "quality.sourcing": RecommendationCategory.retrieval,
    "reasoning.choices": RecommendationCategory.tools,
    "reasoning.steps": RecommendationCategory.orchestration,
    "cost.estimated_cost": RecommendationCategory.model,
    "cost.tokens": RecommendationCategory.model,
    "latency.total": RecommendationCategory.orchestration,
}
DIMENSION_CATEGORIES: dict[Dimension, RecommendationCategory] = {
    Dimension.quality: RecommendationCategory.system_prompt,
    Dimension.coherence: RecommendationCategory.system_prompt,
    Dimension.reasoning: RecommendationCategory.system_prompt,
    Dimension.safety: RecommendationCategory.rule,
    Dimension.ux: RecommendationCategory.output_format,
    Dimension.cost: RecommendationCategory.model,
    Dimension.latency: RecommendationCategory.orchestration,
    Dimension.robustness: RecommendationCategory.system_prompt,
}
CATEGORY_TITLES: dict[RecommendationCategory, tuple[str, str]] = {
    RecommendationCategory.system_prompt: (
        "Améliorer le prompt système",
        "Clarifier l'objectif, les éléments attendus et les critères de qualité dans le prompt système.",
    ),
    RecommendationCategory.rule: (
        "Renforcer les règles de sécurité",
        "Expliciter les règles de sécurité et de conformité et ajouter des contrôles automatiques.",
    ),
    RecommendationCategory.retrieval: (
        "Améliorer la récupération d'informations",
        "Récupérer des documents plus pertinents et ancrer la réponse dans ces sources.",
    ),
    RecommendationCategory.model: (
        "Optimiser le choix du modèle",
        "Le coût est élevé au regard des cibles : réduire le contexte, limiter les tours ou "
        "utiliser un modèle moins coûteux pour les étapes simples.",
    ),
    RecommendationCategory.context: (
        "Enrichir le contexte",
        "Fournir à l'agent les informations nécessaires à une réponse complète.",
    ),
    RecommendationCategory.tools: (
        "Améliorer l'usage des outils",
        "Clarifier les outils disponibles et les situations où les utiliser.",
    ),
    RecommendationCategory.orchestration: (
        "Optimiser l'orchestration",
        "La latence est élevée : réduire le nombre d'étapes, paralléliser et fixer des délais.",
    ),
    RecommendationCategory.memory: (
        "Fiabiliser la mémoire",
        "Mettre à jour et horodater les informations mémorisées.",
    ),
    RecommendationCategory.output_format: (
        "Améliorer la présentation de la réponse",
        "Structurer la réponse (titres, listes, longueur adaptée) et imposer un gabarit de sortie.",
    ),
}


def error_label(code: str, labels: Mapping[str, str] | None = None) -> str:
    if labels and code in labels:
        return labels[code]
    info = BUILTIN_ERROR_TYPES.get(code)
    return info.label if info else code


def criterion_label(c: FeedbackCriterion) -> str:
    return c.name or c.key


def _severity_priority(severity: ErrorSeverity, count: int, n_runs: int) -> Priority:
    rank = SEVERITY_RANK[ErrorSeverity(severity)]
    if rank >= SEVERITY_RANK[ErrorSeverity.critical]:
        return Priority.p0
    if rank >= SEVERITY_RANK[ErrorSeverity.high]:
        return Priority.p0 if n_runs > 1 and count / n_runs >= 0.5 else Priority.p1
    if rank >= SEVERITY_RANK[ErrorSeverity.medium]:
        return Priority.p1 if count >= 2 else Priority.p2
    return Priority.p2


def group_errors(
    errors: Sequence[FeedbackError], labels: Mapping[str, str] | None = None
) -> list[dict[str, Any]]:
    buckets: dict[str, list[FeedbackError]] = defaultdict(list)
    for error in errors:
        buckets[error.type].append(error)
    groups: list[dict[str, Any]] = []
    for code, items in buckets.items():
        worst = max(items, key=lambda e: SEVERITY_RANK[ErrorSeverity(e.severity)])
        examples: list[str] = []
        for item in items:
            text = one_line(item.description, 300)
            if text and text not in examples:
                examples.append(text)
            if len(examples) >= MAX_EXAMPLES:
                break
        evidence = [ref for item in items for ref in item.evidence][:MAX_EVIDENCE]
        groups.append(
            {
                "type": code,
                "label": error_label(code, labels),
                "severity": ErrorSeverity(worst.severity).value,
                "count": len(items),
                "runs": len({i.run_id for i in items if i.run_id}) or None,
                "description": examples[0] if examples else error_label(code, labels),
                "examples": examples,
                "criteria": sorted({i.criterion_key for i in items if i.criterion_key}),
                "evidence": [to_dict(ref) for ref in evidence],
            }
        )
    groups.sort(key=lambda g: (-SEVERITY_RANK[ErrorSeverity(g["severity"])], -g["count"], g["type"]))
    return groups


@dataclass(slots=True)
class _Draft:
    category: RecommendationCategory
    title: str
    description: str
    rationale: list[str] = field(default_factory=list)
    priority: Priority = Priority.p2
    errors: list[str] = field(default_factory=list)
    criteria: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    weight: int = 0  # ordering within the same priority (severity × count)


def _merge(drafts: dict[RecommendationCategory, _Draft], draft: _Draft) -> None:
    existing = drafts.get(draft.category)
    if existing is None:
        drafts[draft.category] = draft
        return
    if PRIORITY_RANK[draft.priority] < PRIORITY_RANK[existing.priority]:
        existing.title, existing.description = draft.title, draft.description
        existing.priority = draft.priority
    existing.rationale.extend(r for r in draft.rationale if r not in existing.rationale)
    existing.errors.extend(e for e in draft.errors if e not in existing.errors)
    existing.criteria.extend(c for c in draft.criteria if c not in existing.criteria)
    existing.evidence.extend(draft.evidence[: max(0, MAX_EVIDENCE - len(existing.evidence))])
    existing.weight += draft.weight


def build_recommendations(
    data: FeedbackInput, error_groups: Sequence[dict[str, Any]]
) -> list[FeedbackRecommendation]:
    drafts: dict[RecommendationCategory, _Draft] = {}
    evidence_by_type: dict[str, list[EvidenceRef]] = defaultdict(list)
    for error in data.errors:
        evidence_by_type[error.type].extend(error.evidence)
    for group in error_groups:
        code = group["type"]
        text = ERROR_RECOMMENDATIONS.get(code)
        severity = ErrorSeverity(group["severity"])
        if text is None:
            info = BUILTIN_ERROR_TYPES.get(code)
            category = DIMENSION_CATEGORIES.get(
                info.dimension if info else Dimension.quality, RecommendationCategory.system_prompt
            )
            title, description = CATEGORY_TITLES[category]
        else:
            category, title, description = text.category, text.title, text.description
        frequency = (
            f"{group['count']} occurrence(s)"
            if data.n_runs <= 1
            else f"{group['count']} occurrence(s) sur {group.get('runs') or '?'} run(s) / {data.n_runs}"
        )
        _merge(
            drafts,
            _Draft(
                category=category,
                title=title,
                description=description,
                rationale=[f"{group['label']} ({code}) : {frequency}, gravité max {severity.value}."],
                priority=_severity_priority(severity, int(group["count"]), data.n_runs),
                errors=[code],
                criteria=list(group["criteria"]),
                evidence=evidence_by_type[code][:MAX_EVIDENCE],
                weight=(SEVERITY_RANK[severity] + 1) * int(group["count"]),
            ),
        )
    for criterion in data.criteria:
        if criterion.value >= WEAKNESS_MAX:
            continue
        is_metric = criterion.key in CRITERION_CATEGORIES and criterion.key.split(".")[0] in (
            "cost",
            "latency",
        )
        if is_metric and criterion.value >= METRIC_ALERT_MAX:
            continue
        category = CRITERION_CATEGORIES.get(criterion.key) or DIMENSION_CATEGORIES.get(
            criterion.dimension or Dimension.quality, RecommendationCategory.system_prompt
        )
        title, description = CATEGORY_TITLES[category]
        priority = Priority.p1 if criterion.value < 0.4 else Priority.p2
        _merge(
            drafts,
            _Draft(
                category=category,
                title=title,
                description=description,
                rationale=[f"Critère faible : {criterion_label(criterion)} = {fr_number(criterion.value)}."],
                priority=priority,
                criteria=[criterion.key],
                weight=1,
            ),
        )
    if data.gate_failures:
        for draft in drafts.values():
            if draft.category == RecommendationCategory.rule:
                draft.priority = Priority.p0
    ordered = sorted(drafts.values(), key=lambda d: (PRIORITY_RANK[d.priority], -d.weight, d.category.value))
    return [
        FeedbackRecommendation(
            category=d.category,
            title=d.title,
            description=d.description,
            rationale=" ".join(d.rationale),
            priority=d.priority,
            related_errors=d.errors,
            related_criteria=sorted(set(d.criteria)),
            evidence=d.evidence[:MAX_EVIDENCE],
        )
        for d in ordered
    ]


def _summary(
    data: FeedbackInput, strengths: int, weaknesses: int, groups: Sequence[dict[str, Any]], first: str | None
) -> str:
    parts: list[str] = []
    prefix = f"{data.label} — " if data.label else ""
    if data.n_runs > 1:
        score = (
            f"score moyen {fr_number(data.score, 1)}/100"
            if data.score is not None
            else "score non disponible"
        )
        parts.append(f"{prefix}Sur {data.n_runs} runs : {score}.")
    elif data.score is not None:
        status = "" if data.passed is None else (" — réussi" if data.passed else " — échoué")
        parts.append(f"{prefix}Score global {fr_number(data.score, 1)}/100{status}.")
    else:
        parts.append(f"{prefix}Score global non disponible.")
    if data.run_failed:
        parts.append(f"Exécution en échec : {one_line(data.run_failed, 200)}.")
    if data.gate_failures:
        parts.append(f"Garde-fou(x) déclenché(s) : {'; '.join(data.gate_failures[:3])}.")
    parts.append(f"{strengths} point(s) fort(s), {weaknesses} point(s) faible(s).")
    total = sum(int(g["count"]) for g in groups)
    if total:
        critical = sum(int(g["count"]) for g in groups if g["severity"] == ErrorSeverity.critical.value)
        detail = f" dont {critical} critique(s)" if critical else ""
        parts.append(f"{total} erreur(s) détectée(s){detail} ({len(groups)} type(s)).")
    else:
        parts.append("Aucune erreur détectée.")
    if first:
        parts.append(f"Priorité : {first}.")
    return " ".join(parts)


def build_feedback(data: FeedbackInput) -> FeedbackReportData:
    """Report for one run (or for pre-aggregated data with ``n_runs > 1``)."""
    ordered = sorted(data.criteria, key=lambda c: (-c.value, c.key))
    strengths = [
        f"{criterion_label(c)} ({c.key}) : {fr_number(c.value)}" for c in ordered if c.value >= STRENGTH_MIN
    ]
    weaknesses = [
        f"{criterion_label(c)} ({c.key}) : {fr_number(c.value)}"
        for c in sorted(data.criteria, key=lambda c: (c.value, c.key))
        if c.value < WEAKNESS_MAX
    ]
    groups = group_errors(data.errors, data.error_labels)
    recommendations = build_recommendations(data, groups)
    actions = [
        f"[{r.priority.value.upper()}] {r.title}" for r in recommendations if r.priority != Priority.p2
    ]
    if not actions:
        actions = [f"[{r.priority.value.upper()}] {r.title}" for r in recommendations]
    actions = actions[:MAX_PRIORITY_ACTIONS]
    first = recommendations[0].title if recommendations else None
    return FeedbackReportData(
        summary=_summary(data, len(strengths), len(weaknesses), groups, first),
        score=None if data.score is None else round(float(data.score), 4),
        strengths=strengths,
        weaknesses=weaknesses,
        errors=groups,
        recommendations=recommendations,
        priority_actions=actions,
        generator=DETERMINISTIC,
    )


def build_group_feedback(inputs: Sequence[FeedbackInput], *, label: str = "") -> FeedbackReportData:
    """Report over a set of runs: mean composite, mean criteria, errors counted across runs."""
    if not inputs:
        return build_feedback(FeedbackInput(score=None, n_runs=0, label=label))
    scores = [i.score for i in inputs if i.score is not None]
    criteria: dict[str, list[FeedbackCriterion]] = defaultdict(list)
    for item in inputs:
        for criterion in item.criteria:
            criteria[criterion.key].append(criterion)
    merged_criteria = [
        FeedbackCriterion(
            key=key,
            value=math.fsum(c.value for c in items) / len(items),
            name=items[0].name,
            dimension=items[0].dimension,
        )
        for key, items in criteria.items()
    ]
    labels: dict[str, str] = {}
    for item in inputs:
        labels.update(item.error_labels)
    failed_runs = [i for i in inputs if i.run_failed]
    gate_runs = [i for i in inputs if i.gate_failures]
    gate_failures = (
        [f"{len(gate_runs)} run(s) invalidé(s) ou plafonné(s) par un garde-fou"] if gate_runs else []
    )
    data = FeedbackInput(
        score=(math.fsum(scores) / len(scores)) if scores else None,
        passed=None,
        criteria=merged_criteria,
        errors=[e for i in inputs for e in i.errors],
        gate_failures=gate_failures,
        run_failed=f"{len(failed_runs)} run(s) en échec d'exécution" if failed_runs else None,
        n_runs=len(inputs),
        error_labels=labels,
        label=label,
    )
    return build_feedback(data)


def feedback_criteria(
    values: Mapping[str, float],
    names: Mapping[str, str] | None = None,
    dimensions: Mapping[str, Dimension] | None = None,
) -> list[FeedbackCriterion]:
    """Helper: criterion values (0–1) → :class:`FeedbackCriterion` list."""
    names = names or {}
    dimensions = dimensions or {}
    result = []
    for key, value in values.items():
        dimension = dimensions.get(key)
        if dimension is None:
            try:
                dimension = Dimension(key.split(".", 1)[0])
            except ValueError:
                dimension = None
        result.append(
            FeedbackCriterion(key=key, value=float(value), name=names.get(key, ""), dimension=dimension)
        )
    return result


def dimension_label(dimension: Dimension | str) -> str:
    try:
        return DIMENSION_LABELS[Dimension(dimension)]
    except ValueError:
        return str(dimension)
