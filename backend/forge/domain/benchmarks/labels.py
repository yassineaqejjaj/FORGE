"""French labels of the analytics groupings (shared by benchmarks, experiments and the API)."""

from __future__ import annotations

from forge.domain.enums import DIMENSION_LABELS, SCENARIO_CATEGORIES, Difficulty, Dimension

UNKNOWN_KEY = "unknown"

DIFFICULTY_LABELS: dict[str, str] = {
    Difficulty.easy: "Facile",
    Difficulty.medium: "Moyen",
    Difficulty.hard: "Difficile",
    Difficulty.expert: "Expert",
}
DIFFICULTY_ORDER: dict[str, int] = {d.value: i for i, d in enumerate(Difficulty)}

VISIBILITY_LABELS: dict[str, str] = {
    "public": "Public",
    "private": "Privé",
    "fresh": "Récent (fresh)",
}

DIMENSION_ORDER: dict[str, int] = {d.value: i for i, d in enumerate(Dimension)}

RESOURCE_LABELS: dict[str, str] = {
    "cost": "Coût moyen par run",
    "latency": "Latence moyenne",
    "tokens": "Tokens moyens par run",
}


def dimension_label(key: str) -> str:
    try:
        return DIMENSION_LABELS[Dimension(key)]
    except ValueError:
        return key


def category_label(key: str) -> str:
    return SCENARIO_CATEGORIES.get(key, key or "Sans catégorie")


def difficulty_label(key: str) -> str:
    return DIFFICULTY_LABELS.get(key, key or "Non renseignée")


def visibility_label(key: str) -> str:
    return VISIBILITY_LABELS.get(key, key)


def model_label(key: str | None) -> str:
    return key if key and key != UNKNOWN_KEY else "Modèle non renseigné"


def agent_name_from_label(label: str) -> str:
    """``"ProductAgent v1.3"`` → ``"ProductAgent"`` (labels are built as ``"<name> v<version>"``)."""
    name, sep, _version = label.rpartition(" v")
    return name if sep and name else label


def dimension_sort_key(key: str) -> tuple[int, str]:
    return DIMENSION_ORDER.get(key, len(DIMENSION_ORDER)), key
