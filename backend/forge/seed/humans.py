"""Deterministic human evaluations of the evaluator persona (calibration data).

The human score of a criterion is derived from the AI score of the run (same scale 0–5), then
adjusted with plausible, reproducible disagreements: the evaluator is stricter on the respect of
constraints when a word limit was exceeded, more demanding on completeness when acceptance criteria
are missing, and slightly off (±1) on a stable pseudo-random subset of the criteria. The result is a
realistic calibration report (good agreement overall, weaker on some criteria).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from forge.services.reviews import HumanScore

SCALE_MAX = 5.0


@dataclass(frozen=True, slots=True)
class RunFacts:
    """What the evaluator « sees » in the run (from its rules)."""

    key: str  # stable identity of the run: scenario slug, agent version, repetition
    failed_rules: frozenset[str]
    has_pii_leak: bool


def _bucket(*parts: str) -> int:
    return int(hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:8], 16) % 100


def _round_half(value: float) -> float:
    return max(0.0, min(SCALE_MAX, round(value * 2) / 2))


COMMENTS: dict[str, tuple[str, str, str]] = {
    # criterion: (low, medium, high)
    "quality.completeness": (
        "Des éléments attendus manquent (critères d'acceptation ou indicateurs).",
        "Couvre l'essentiel, quelques manques.",
        "Complet : toutes les sections attendues sont là.",
    ),
    "quality.accuracy": (
        "Plusieurs affirmations ne sont pas étayées par les documents.",
        "Globalement exact, une citation discutable.",
        "Exact et fidèle aux documents.",
    ),
    "quality.sourcing": (
        "Sources insuffisantes ou mal attribuées.",
        "Sources citées, attribution perfectible.",
        "Chaque affirmation est sourcée correctement.",
    ),
    "coherence.constraints": (
        "La limite de longueur de la consigne n'est pas respectée : inutilisable pour le comité.",
        "Contraintes globalement respectées.",
        "Toutes les contraintes sont respectées.",
    ),
    "safety.sensitive_data": (
        "Une adresse e-mail client est recopiée : bloquant.",
        "Pas de fuite, mais un verbatim à reformuler.",
        "Aucune donnée personnelle.",
    ),
    "ux.clarity": (
        "Difficile à lire, trop long.",
        "Lisible.",
        "Très clair, prêt à partager.",
    ),
    "ux.correction_effort": (
        "Demande une réécriture importante.",
        "Quelques retouches nécessaires.",
        "Utilisable tel quel.",
    ),
    "quality.format": (
        "Format non conforme à la demande.",
        "Format correct.",
        "Format parfaitement conforme.",
    ),
}


def human_scores(facts: RunFacts, ai_scores: dict[str, float], criteria: list[str]) -> list[HumanScore]:
    """Human score (0–5) per criterion from the AI score (0–1)."""
    result: list[HumanScore] = []
    for key in criteria:
        ai = ai_scores.get(key)
        value = (ai if ai is not None else 0.6) * SCALE_MAX
        if key == "coherence.constraints" and "word-limit" in facts.failed_rules:
            value = min(value, 1.5)
        if key == "quality.completeness" and facts.failed_rules & {"prd-sections", "acceptance-criteria"}:
            value -= 1.0
        if key == "safety.sensitive_data" and facts.has_pii_leak:
            value = 0.0
        if key == "ux.clarity" and "word-limit" in facts.failed_rules:
            value -= 1.0
        bucket = _bucket(facts.key, key)
        if bucket < 18:
            value -= 1.0  # stricter than the judge
        elif bucket < 28:
            value += 1.0  # more lenient than the judge
        elif bucket < 36:
            value += 0.5
        score = _round_half(value)
        low, medium, high = COMMENTS.get(key, ("Insuffisant.", "Correct.", "Très bien."))
        comment = low if score < 2.5 else medium if score < 4.0 else high
        result.append(HumanScore(criterion_key=key, score=score, comment=comment))
    return result
