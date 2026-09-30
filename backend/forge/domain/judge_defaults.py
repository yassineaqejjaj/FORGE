"""Default LLM judge prompts (seeded into the ``forge-judge`` judges at bootstrap).

Contract of ``rubric_template`` (rendered by ``forge.domain.judges.prompting``) — placeholders:

``{scenario_name}`` ``{scenario_description}`` ``{category}`` ``{difficulty}`` ``{input}``
``{context}`` ``{constraints}`` ``{expected_output}`` ``{expected_behavior}`` ``{output}``
``{trace}`` (compact timeline, one line per event prefixed with ``[E<seq>]``) ``{criteria}``
(numbered list: key, name, question, rubric, scale) ``{error_types}`` (taxonomy codes + labels).

The judge must answer with the JSON document described in ``JUDGE_OUTPUT_SCHEMA``.
"""

from __future__ import annotations

DEFAULT_JUDGE_SYSTEM_PROMPT = """Tu es un évaluateur expert, rigoureux et impartial d'agents IA.
Tu évalues la réponse d'un agent à un scénario de test, critère par critère, selon la grille fournie.

Règles :
- Évalue uniquement ce qui est observable dans la sortie et la trace d'exécution fournies.
- Chaque note doit être justifiée par des éléments précis (citations courtes de la sortie, ou
  références d'étapes de trace au format [E12]).
- Ne sois pas influencé par la longueur ou le ton de la réponse : seule la qualité compte.
- Signale chaque erreur détectée avec un type de la taxonomie, une gravité et une preuve.
- Indique ton niveau de confiance (0 à 1) : baisse-le si l'information manque pour juger.
- Réponds UNIQUEMENT avec un objet JSON valide conforme au schéma demandé, sans texte autour."""

DEFAULT_RUBRIC_TEMPLATE = """# Scénario : {scenario_name}
Catégorie : {category} · Difficulté : {difficulty}

{scenario_description}

## Demande reçue par l'agent
{input}

## Contexte fourni à l'agent
{context}

## Contraintes à respecter
{constraints}

## Résultat attendu (référence, non visible par l'agent)
{expected_output}

## Comportement attendu
{expected_behavior}

## Trace d'exécution
{trace}

## Sortie finale de l'agent
{output}

## Critères à évaluer
{criteria}

## Taxonomie des erreurs
{error_types}

Évalue chaque critère listé. Pour chacun, donne : la note (dans l'échelle indiquée), une
justification factuelle, les preuves (extraits courts ou références [E<n>]), les erreurs détectées
et ta confiance."""

#: JSON schema the judge answer must follow (also used for structured outputs when supported).
JUDGE_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["criteria"],
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "score", "justification", "confidence"],
                "properties": {
                    "key": {"type": "string"},
                    "score": {"type": "number"},
                    "justification": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "excerpt": {"type": "string"},
                                "event": {"type": "integer", "description": "numéro d'étape [E<n>]"},
                            },
                        },
                    },
                    "errors": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["type", "severity", "description"],
                            "properties": {
                                "type": {"type": "string"},
                                "severity": {"enum": ["low", "medium", "high", "critical"]},
                                "description": {"type": "string"},
                                "excerpt": {"type": "string"},
                                "event": {"type": "integer"},
                            },
                        },
                    },
                },
            },
        },
        "summary": {"type": "string"},
    },
}
