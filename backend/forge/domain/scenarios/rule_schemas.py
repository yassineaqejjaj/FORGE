"""JSON schema of the ``params`` of every rule type (docs/ARCHITECTURE.md §7.2).

The schemas are the contract between the Scenario Manager (validation at creation), the rules engine
(``forge.domain.rules``) and the UI (``GET /meta`` exposes them to build the rule editor).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge.domain.defaults import RULE_DEFAULTS
from forge.domain.enums import PiiType, RuleType

_POSITIVE_INT: dict[str, Any] = {"type": "integer", "minimum": 1}
_NON_NEGATIVE_INT: dict[str, Any] = {"type": "integer", "minimum": 0}
_STRING_LIST: dict[str, Any] = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1}


def _obj(properties: dict[str, Any], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        schema["required"] = required
    schema.update(extra)
    return schema


_REGEX = _obj(
    {
        "pattern": {"type": "string", "minLength": 1, "description": "Expression régulière (syntaxe Python)"},
        "flags": {"type": "string", "pattern": "^[ims]*$", "description": "Options : i, m, s"},
    },
    ["pattern"],
)
_KEYWORDS = _obj(
    {
        "keywords": {**_STRING_LIST, "description": "Mots-clés recherchés dans la sortie"},
        "mode": {"type": "string", "enum": ["all", "any"], "default": "all"},
        "case_sensitive": {"type": "boolean", "default": False},
    },
    ["keywords"],
)
_LENGTH = _obj(
    {
        "words": {**_NON_NEGATIVE_INT, "description": "Nombre de mots"},
        "chars": {**_NON_NEGATIVE_INT, "description": "Nombre de caractères"},
    },
    anyOf=[{"required": ["words"]}, {"required": ["chars"]}],
)
_TOOL = _obj(
    {
        "tool": {"type": "string", "minLength": 1, "description": "Nom de l'outil"},
        "min": {**_POSITIVE_INT, "description": "Nombre minimal d'appels (tool_called)"},
    },
    ["tool"],
)

RULE_PARAM_SCHEMAS: dict[RuleType, dict[str, Any]] = {
    RuleType.required_fields: _obj(
        {"fields": {**_STRING_LIST, "description": "Chemins JSON requis (« a.b[0].c »)"}}, ["fields"]
    ),
    RuleType.json_valid: _obj({}),
    RuleType.json_schema: _obj(
        {"schema": {"type": "object", "description": "Schéma JSON (draft 2020-12) de la sortie"}}, ["schema"]
    ),
    RuleType.regex_match: _REGEX,
    RuleType.regex_absent: _REGEX,
    RuleType.contains: _KEYWORDS,
    RuleType.not_contains: _KEYWORDS,
    RuleType.sections_present: _obj(
        {"sections": {**_STRING_LIST, "description": "Titres Markdown attendus"}}, ["sections"]
    ),
    RuleType.citation_required: _obj(
        {
            "min": {**_POSITIVE_INT, "default": 1, "description": "Nombre minimal de citations"},
            "pattern": {"type": "string", "minLength": 1, "description": "Motif de citation personnalisé"},
        }
    ),
    RuleType.source_present: _obj(
        {"min": {**_POSITIVE_INT, "default": 1, "description": "Documents du contexte à citer"}}
    ),
    RuleType.no_pii: _obj(
        {
            "types": {
                "type": "array",
                "items": {"type": "string", "enum": [t.value for t in PiiType]},
                "description": "Types de données personnelles recherchés (tous par défaut)",
            },
            "allow": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Valeurs autorisées (ex. adresse de support publique)",
            },
        }
    ),
    RuleType.expected_value: _obj(
        {
            "path": {"type": "string", "minLength": 1, "description": "Chemin JSON dans la sortie"},
            "value": {"description": "Valeur attendue (comparaison JSON)"},
        },
        ["path", "value"],
    ),
    RuleType.max_length: _LENGTH,
    RuleType.min_length: _LENGTH,
    RuleType.tool_called: _TOOL,
    RuleType.tool_not_called: _TOOL,
    RuleType.max_tool_calls: _obj(
        {"max": {**_NON_NEGATIVE_INT, "description": "Nombre maximal d'appels d'outils"}}, ["max"]
    ),
    RuleType.max_latency: _obj(
        {"ms": {"type": "number", "exclusiveMinimum": 0, "description": "Latence maximale (ms)"}}, ["ms"]
    ),
    RuleType.max_cost: _obj(
        {"max": {"type": "number", "minimum": 0, "description": "Coût estimé maximal"}}, ["max"]
    ),
    RuleType.no_canary: _obj({}),
}


@dataclass(frozen=True, slots=True)
class RuleTypeInfo:
    type: RuleType
    label: str
    description: str
    example: dict[str, Any]


RULE_TYPE_INFO: dict[RuleType, RuleTypeInfo] = {
    info.type: info
    for info in (
        RuleTypeInfo(RuleType.required_fields, "Champs requis",
                     "Les chemins JSON listés existent dans la sortie JSON (score = part présente).",
                     {"fields": ["title", "requirements[0].id"]}),
        RuleTypeInfo(RuleType.json_valid, "JSON valide",
                     "La sortie (ou son bloc ```json```) est un JSON valide.", {}),
        RuleTypeInfo(RuleType.json_schema, "Schéma JSON",
                     "La sortie JSON respecte le schéma fourni.",
                     {"schema": {"type": "object", "required": ["title"]}}),
        RuleTypeInfo(RuleType.regex_match, "Motif présent",
                     "L'expression régulière est trouvée dans la sortie.", {"pattern": "^# ", "flags": "m"}),
        RuleTypeInfo(RuleType.regex_absent, "Motif absent",
                     "L'expression régulière n'apparaît pas dans la sortie.",
                     {"pattern": "TODO", "flags": "i"}),
        RuleTypeInfo(RuleType.contains, "Mots-clés présents",
                     "Les mots-clés apparaissent dans la sortie (score = part trouvée).",
                     {"keywords": ["objectifs", "périmètre"], "mode": "all", "case_sensitive": False}),
        RuleTypeInfo(RuleType.not_contains, "Mots-clés interdits",
                     "Aucun des mots-clés n'apparaît dans la sortie.",
                     {"keywords": ["garanti à 100 %"], "mode": "any"}),
        RuleTypeInfo(RuleType.sections_present, "Sections présentes",
                     "Les titres Markdown attendus sont présents (insensible à la casse et aux accents).",
                     {"sections": ["Objectifs", "Critères d'acceptation"]}),
        RuleTypeInfo(RuleType.citation_required, "Citations requises",
                     "La sortie contient au moins `min` citations ([1], [source: …], [doc-id]).", {"min": 2}),
        RuleTypeInfo(RuleType.source_present, "Sources du contexte citées",
                     "La sortie cite au moins `min` documents du contexte (id ou titre).", {"min": 1}),
        RuleTypeInfo(RuleType.no_pii, "Aucune donnée personnelle",
                     "Aucune donnée personnelle (e-mail, téléphone, IBAN, carte, NIR, IP, personne).",
                     {"types": ["EMAIL", "PHONE"], "allow": ["support@example.com"]}),
        RuleTypeInfo(RuleType.expected_value, "Valeur attendue",
                     "La valeur au chemin JSON est égale à la valeur attendue.",
                     {"path": "priority", "value": "P1"}),
        RuleTypeInfo(RuleType.max_length, "Longueur maximale",
                     "La sortie ne dépasse pas le nombre de mots ou de caractères.", {"words": 400}),
        RuleTypeInfo(RuleType.min_length, "Longueur minimale",
                     "La sortie atteint le nombre de mots ou de caractères.", {"words": 150}),
        RuleTypeInfo(RuleType.tool_called, "Outil appelé",
                     "La trace contient au moins `min` appels de l'outil.",
                     {"tool": "search_docs", "min": 1}),
        RuleTypeInfo(RuleType.tool_not_called, "Outil non appelé",
                     "La trace ne contient aucun appel de l'outil.", {"tool": "send_email"}),
        RuleTypeInfo(RuleType.max_tool_calls, "Appels d'outils limités",
                     "Le nombre total d'appels d'outils ne dépasse pas `max`.", {"max": 5}),
        RuleTypeInfo(RuleType.max_latency, "Latence maximale",
                     "La latence totale du run ne dépasse pas `ms` millisecondes.", {"ms": 15000}),
        RuleTypeInfo(RuleType.max_cost, "Coût maximal",
                     "Le coût estimé du run ne dépasse pas `max`.", {"max": 0.05}),
        RuleTypeInfo(RuleType.no_canary, "Aucun canari",
                     "La sortie ne contient aucun canari FORGE-CANARY-… (contamination du benchmark).", {}),
    )
}  # fmt: skip


def rule_type_catalog() -> list[dict[str, Any]]:
    """Rule types with label, params schema, example and default criterion / error type (``/meta``)."""
    catalog: list[dict[str, Any]] = []
    for rule_type in RuleType:
        info = RULE_TYPE_INFO[rule_type]
        criterion, error_type = RULE_DEFAULTS[rule_type]
        catalog.append(
            {
                "type": rule_type.value,
                "label": info.label,
                "description": info.description,
                "params_schema": RULE_PARAM_SCHEMAS[rule_type],
                "example": info.example,
                "default_criterion": criterion,
                "default_error_type": str(error_type) if error_type else None,
            }
        )
    return catalog
