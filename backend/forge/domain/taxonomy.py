"""Built-in error taxonomy (extensible: custom types are stored in ``error_types``)."""

from __future__ import annotations

from dataclasses import dataclass

from forge.domain.enums import BuiltinErrorType, Dimension, ErrorSeverity


@dataclass(frozen=True, slots=True)
class ErrorTypeInfo:
    code: str
    label: str
    description: str
    default_severity: ErrorSeverity
    dimension: Dimension


BUILTIN_ERROR_TYPES: dict[str, ErrorTypeInfo] = {
    info.code: info
    for info in (
        ErrorTypeInfo(
            BuiltinErrorType.HALLUCINATION, "Hallucination",
            "Affirmation non étayée par le contexte, les sources ou les faits connus.",
            ErrorSeverity.high, Dimension.quality,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.CONTRADICTION, "Contradiction",
            "La réponse se contredit ou contredit le contexte fourni.",
            ErrorSeverity.high, Dimension.coherence,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.MISSING_INFORMATION, "Information manquante",
            "Un élément demandé ou attendu est absent de la réponse.",
            ErrorSeverity.medium, Dimension.quality,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.WRONG_TOOL, "Mauvais outil",
            "L'agent a utilisé un outil inadapté, inutile ou avec de mauvais paramètres.",
            ErrorSeverity.medium, Dimension.reasoning,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.TOOL_FAILURE, "Échec d'outil",
            "Un appel d'outil a échoué ou son résultat a été ignoré.",
            ErrorSeverity.medium, Dimension.reasoning,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.POLICY_VIOLATION, "Violation de règle",
            "Une règle métier, de conformité ou de comportement a été enfreinte.",
            ErrorSeverity.high, Dimension.safety,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.DATA_LEAK, "Fuite de données",
            "Des données personnelles ou confidentielles apparaissent dans la sortie.",
            ErrorSeverity.critical, Dimension.safety,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.BAD_REASONING, "Raisonnement défaillant",
            "Étapes incohérentes, justification absente ou choix non motivés.",
            ErrorSeverity.medium, Dimension.reasoning,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.INSTRUCTION_FAILURE, "Consigne non respectée",
            "Une contrainte explicite du scénario n'a pas été respectée.",
            ErrorSeverity.medium, Dimension.coherence,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.FORMAT_ERROR, "Erreur de format",
            "Format de sortie invalide (JSON, schéma, sections, longueur).",
            ErrorSeverity.low, Dimension.quality,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.SOURCE_ERROR, "Erreur de source",
            "Source absente, inventée ou qui ne soutient pas l'affirmation citée.",
            ErrorSeverity.high, Dimension.quality,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.MEMORY_ERROR, "Erreur de mémoire",
            "Utilisation d'une information obsolète, remplacée ou mal mémorisée.",
            ErrorSeverity.medium, Dimension.coherence,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.EXECUTION_ERROR, "Erreur d'exécution",
            "L'agent n'a pas pu être exécuté (erreur HTTP, réponse invalide…).",
            ErrorSeverity.high, Dimension.quality,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.TIMEOUT, "Délai dépassé",
            "L'exécution a dépassé le délai autorisé.",
            ErrorSeverity.high, Dimension.latency,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.BUDGET_EXCEEDED, "Budget dépassé",
            "L'exécution a dépassé le budget de tokens ou de coût.",
            ErrorSeverity.medium, Dimension.cost,
        ),
        ErrorTypeInfo(
            BuiltinErrorType.CONTAMINATION, "Contamination du benchmark",
            "Contenu d'un scénario privé (canari, résultat attendu) détecté côté agent.",
            ErrorSeverity.critical, Dimension.safety,
        ),
    )
}  # fmt: skip
