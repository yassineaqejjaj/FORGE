"""JSON schemas of each rule type's ``params`` (exposed by ``GET /meta`` for rule editors)."""

from __future__ import annotations

from typing import Any

from forge.domain.enums import PiiType, RuleType

_STRINGS: dict[str, Any] = {"type": "array", "items": {"type": "string"}, "minItems": 1}
_REGEX: dict[str, Any] = {
    "pattern": {"type": "string", "description": "Expression régulière (syntaxe Python)"},
    "flags": {"type": "string", "description": "Options : i (casse), m (multiligne), s (point = tout)"},
}


def _obj(properties: dict[str, Any], required: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    schema.update(extra)
    return schema


RULE_PARAM_SCHEMAS: dict[RuleType, dict[str, Any]] = {
    RuleType.required_fields: _obj(
        {"fields": {**_STRINGS, "description": "Chemins JSON (a.b[0].c) devant être présents"}}, ["fields"]
    ),
    RuleType.json_valid: _obj({}),
    RuleType.json_schema: _obj({"schema": {"type": "object", "description": "JSON Schema"}}, ["schema"]),
    RuleType.regex_match: _obj(_REGEX, ["pattern"]),
    RuleType.regex_absent: _obj(_REGEX, ["pattern"]),
    RuleType.contains: _obj(
        {
            "keywords": _STRINGS,
            "mode": {"enum": ["all", "any"], "default": "all"},
            "case_sensitive": {"type": "boolean", "default": False},
        },
        ["keywords"],
    ),
    RuleType.not_contains: _obj(
        {"keywords": _STRINGS, "case_sensitive": {"type": "boolean", "default": False}}, ["keywords"]
    ),
    RuleType.sections_present: _obj(
        {"sections": {**_STRINGS, "description": "Titres Markdown attendus (insensible casse/accents)"}},
        ["sections"],
    ),
    RuleType.citation_required: _obj({"min": {"type": "integer", "minimum": 1, "default": 1}, **_REGEX}),
    RuleType.source_present: _obj({"min": {"type": "integer", "minimum": 1, "default": 1}}),
    RuleType.no_pii: _obj(
        {
            "types": {"type": "array", "items": {"enum": [t.value for t in PiiType]}},
            "allow": {"type": "array", "items": {"type": "string"}, "description": "Valeurs autorisées"},
        }
    ),
    RuleType.expected_value: _obj({"path": {"type": "string"}, "value": {}}, ["path", "value"]),
    RuleType.max_length: _obj(
        {"words": {"type": "integer", "minimum": 0}, "chars": {"type": "integer", "minimum": 0}},
        anyOf=[{"required": ["words"]}, {"required": ["chars"]}],
    ),
    RuleType.min_length: _obj(
        {"words": {"type": "integer", "minimum": 0}, "chars": {"type": "integer", "minimum": 0}},
        anyOf=[{"required": ["words"]}, {"required": ["chars"]}],
    ),
    RuleType.tool_called: _obj(
        {"tool": {"type": "string"}, "min": {"type": "integer", "minimum": 1, "default": 1}}, ["tool"]
    ),
    RuleType.tool_not_called: _obj({"tool": {"type": "string"}}, ["tool"]),
    RuleType.max_tool_calls: _obj({"max": {"type": "integer", "minimum": 0}}, ["max"]),
    RuleType.max_latency: _obj({"ms": {"type": "number", "exclusiveMinimum": 0}}, ["ms"]),
    RuleType.max_cost: _obj({"max": {"type": "number", "minimum": 0}}, ["max"]),
    RuleType.no_canary: _obj({}),
}
