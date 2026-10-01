"""Validation and normalisation of scenario version payloads (docs/ARCHITECTURE.md §5.1, §7.2).

A scenario version content is the JSON object hashed by ``versioning.scenario_version_hash``::

    {description, difficulty, input, context, constraints, expected_output, expected_behavior,
     criteria, rules, tool_mocks, dataset_id}

:func:`normalize_content` validates it and returns the canonical form stored in ``scenario_versions``
(missing rule ids filled with ``R<n>``, defaults applied). Every problem is reported at once
(:class:`ScenarioValidationError.issues`) with a JSON path and a French message.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from forge.domain.enums import Difficulty, Dimension, ErrorSeverity, RuleType
from forge.domain.scenarios.rule_schemas import RULE_PARAM_SCHEMAS

CONTENT_FIELDS: tuple[str, ...] = (
    "description",
    "difficulty",
    "input",
    "context",
    "constraints",
    "expected_output",
    "expected_behavior",
    "criteria",
    "rules",
    "tool_mocks",
    "dataset_id",
)

CRITERION_KEY_RE = re.compile(r"^[a-z]+\.[a-z0-9_]{1,63}$")
#: Scenario slugs: ``scenario_prd_001``, ``scenario_prd_001_variant_short``.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,119}$")
RULE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})
MAX_RULES = 100
MAX_CRITERIA = 50

_RULE_FIELDS = frozenset(
    {
        "id",
        "type",
        "params",
        "description",
        "criterion_key",
        "dimension",
        "severity",
        "error_type",
        "weight",
        "hidden",
    }
)
_CRITERION_FIELDS = frozenset(
    {"key", "dimension", "name", "question", "rubric", "scale_min", "scale_max", "weight"}
)
_MOCK_FIELDS = frozenset({"tool", "response", "match", "error", "latency_ms"})


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"field": self.path, "message": self.message}


class ScenarioValidationError(ValueError):
    """Invalid scenario content. ``issues`` lists every problem (path + French message)."""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        head = "; ".join(f"{i.path} : {i.message}" for i in issues[:3])
        if len(issues) > 3:
            head += f" (+{len(issues) - 3})"
        super().__init__(f"Scénario invalide — {head}")


def is_valid_criterion_key(key: str, catalog: Iterable[str] | None = None) -> bool:
    """Catalog key, or custom key prefixed by a dimension (``quality.my_criterion``)."""
    if catalog is not None and key in set(catalog):
        return True
    if not CRITERION_KEY_RE.match(key):
        return False
    return key.split(".", 1)[0] in {d.value for d in Dimension}


def _num(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


class _Validator:
    def __init__(self, catalog: set[str] | None, error_types: set[str] | None) -> None:
        self.catalog = catalog
        self.error_types = error_types
        self.issues: list[ValidationIssue] = []

    def add(self, path: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, message))

    # --- sections -----------------------------------------------------------------------------

    def input(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            self.add("input", "objet attendu (avec « prompt » ou « messages »)")
            return {}
        prompt = value.get("prompt")
        messages = value.get("messages")
        has_prompt = isinstance(prompt, str) and bool(prompt.strip())
        if prompt is not None and not isinstance(prompt, str):
            self.add("input.prompt", "texte attendu")
        if messages is not None:
            if not isinstance(messages, list) or not messages:
                self.add("input.messages", "liste non vide attendue")
            else:
                for i, message in enumerate(messages):
                    path = f"input.messages[{i}]"
                    if not isinstance(message, dict):
                        self.add(path, "objet {role, content} attendu")
                        continue
                    if message.get("role") not in MESSAGE_ROLES:
                        self.add(f"{path}.role", "rôle attendu : system, user, assistant ou tool")
                    if not isinstance(message.get("content"), str | list):
                        self.add(f"{path}.content", "contenu attendu")
        has_messages = isinstance(messages, list) and bool(messages)
        if not has_prompt and not has_messages:
            self.add("input", "l'entrée doit contenir « prompt » (texte non vide) ou « messages »")
        return dict(value)

    def context(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            self.add("context", "objet attendu")
            return {}
        documents = value.get("documents")
        if documents is not None:
            if not isinstance(documents, list):
                self.add("context.documents", "liste attendue")
            else:
                seen: set[str] = set()
                for i, doc in enumerate(documents):
                    path = f"context.documents[{i}]"
                    if not isinstance(doc, dict):
                        self.add(path, "objet {id, title, content, source} attendu")
                        continue
                    if not (str(doc.get("content") or "").strip() or str(doc.get("title") or "").strip()):
                        self.add(path, "document sans titre ni contenu")
                    doc_id = doc.get("id")
                    if doc_id is not None:
                        if str(doc_id) in seen:
                            self.add(f"{path}.id", f"identifiant de document dupliqué « {doc_id} »")
                        seen.add(str(doc_id))
        return dict(value)

    def constraints(self, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(c, str) for c in value):
            self.add("constraints", "liste de textes attendue")
            return []
        return [c.strip() for c in value if c.strip()]

    def criteria(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            self.add("criteria", "liste attendue")
            return []
        if len(value) > MAX_CRITERIA:
            self.add("criteria", f"au plus {MAX_CRITERIA} critères")
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, item in enumerate(value):
            path = f"criteria[{i}]"
            if isinstance(item, str):
                item = {"key": item}
            if not isinstance(item, dict):
                self.add(path, "objet {key, weight?, question?, rubric?} attendu")
                continue
            unknown = set(item) - _CRITERION_FIELDS
            if unknown:
                self.add(path, f"champ(s) inconnu(s) : {', '.join(sorted(unknown))}")
            key = str(item.get("key") or "").strip()
            if not key:
                self.add(f"{path}.key", "clé de critère requise")
                continue
            if not is_valid_criterion_key(key, self.catalog):
                self.add(
                    f"{path}.key",
                    f"critère inconnu « {key} » (clé du catalogue ou « <dimension>.<nom> » attendue)",
                )
            if key in seen:
                self.add(f"{path}.key", f"critère dupliqué « {key} »")
            seen.add(key)
            dimension = item.get("dimension")
            if dimension is not None and dimension not in {d.value for d in Dimension}:
                self.add(f"{path}.dimension", f"dimension inconnue « {dimension} »")
            weight = item.get("weight")
            if weight is not None and (not _num(weight) or weight < 0):
                self.add(f"{path}.weight", "poids positif attendu")
            smin, smax = item.get("scale_min"), item.get("scale_max")
            for name, bound in (("scale_min", smin), ("scale_max", smax)):
                if bound is not None and not _num(bound):
                    self.add(f"{path}.{name}", "nombre attendu")
            if _num(smin) and _num(smax) and float(smin) >= float(smax):  # type: ignore[arg-type]
                self.add(path, "scale_min doit être inférieur à scale_max")
            for name in ("name", "question", "rubric"):
                if item.get(name) is not None and not isinstance(item.get(name), str):
                    self.add(f"{path}.{name}", "texte attendu")
            result.append({**item, "key": key})
        return result

    def rules(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            self.add("rules", "liste attendue")
            return []
        if len(value) > MAX_RULES:
            self.add("rules", f"au plus {MAX_RULES} règles")
        result: list[dict[str, Any]] = []
        used_ids = {str(r.get("id")) for r in value if isinstance(r, dict) and r.get("id")}
        seen: set[str] = set()
        counter = 0
        for i, item in enumerate(value):
            path = f"rules[{i}]"
            if not isinstance(item, dict):
                self.add(path, "objet {type, params, …} attendu")
                continue
            rule = dict(item)
            unknown = set(rule) - _RULE_FIELDS
            if unknown:
                self.add(path, f"champ(s) inconnu(s) : {', '.join(sorted(unknown))}")
            rule_id = rule.get("id")
            if rule_id is None or rule_id == "":
                counter += 1
                while f"R{counter}" in used_ids or f"R{counter}" in seen:
                    counter += 1
                rule_id = f"R{counter}"
            rule_id = str(rule_id)
            if not RULE_ID_RE.match(rule_id):
                self.add(f"{path}.id", "identifiant invalide (lettres, chiffres, _ . : -)")
            if rule_id in seen:
                self.add(f"{path}.id", f"identifiant de règle dupliqué « {rule_id} »")
            seen.add(rule_id)
            rule["id"] = rule_id
            raw_type = rule.get("type")
            try:
                rule_type = RuleType(str(raw_type))
            except ValueError:
                self.add(f"{path}.type", f"type de règle inconnu « {raw_type} »")
                result.append(rule)
                continue
            params = rule.get("params")
            if params is None:
                params = {}
            if not isinstance(params, dict):
                self.add(f"{path}.params", "objet attendu")
                params = {}
            rule["params"] = params
            self._rule_params(path, rule_type, params)
            criterion = rule.get("criterion_key")
            if criterion is not None and not (
                isinstance(criterion, str) and is_valid_criterion_key(criterion, self.catalog)
            ):
                self.add(f"{path}.criterion_key", f"critère inconnu « {criterion} »")
            dimension = rule.get("dimension")
            if dimension is not None and dimension not in {d.value for d in Dimension}:
                self.add(f"{path}.dimension", f"dimension inconnue « {dimension} »")
            severity = rule.get("severity")
            if severity is not None and severity not in {s.value for s in ErrorSeverity}:
                self.add(f"{path}.severity", "gravité attendue : low, medium, high ou critical")
            error_type = rule.get("error_type")
            if error_type is not None:
                if not isinstance(error_type, str) or not error_type:
                    self.add(f"{path}.error_type", "code d'erreur attendu")
                elif self.error_types is not None and error_type not in self.error_types:
                    self.add(f"{path}.error_type", f"type d'erreur inconnu « {error_type} »")
            weight = rule.get("weight")
            if weight is not None and (not _num(weight) or weight <= 0):
                self.add(f"{path}.weight", "poids strictement positif attendu")
            if rule.get("hidden") is not None and not isinstance(rule.get("hidden"), bool):
                self.add(f"{path}.hidden", "booléen attendu")
            if rule.get("description") is not None and not isinstance(rule.get("description"), str):
                self.add(f"{path}.description", "texte attendu")
            result.append(rule)
        return result

    def _rule_params(self, path: str, rule_type: RuleType, params: dict[str, Any]) -> None:
        validator = Draft202012Validator(RULE_PARAM_SCHEMAS[rule_type])
        for error in sorted(validator.iter_errors(params), key=lambda e: list(e.path)):
            location = ".".join(str(p) for p in error.path)
            self.add(f"{path}.params{'.' + location if location else ''}", _schema_message(error))
        if rule_type in (RuleType.regex_match, RuleType.regex_absent) and isinstance(
            params.get("pattern"), str
        ):
            try:
                re.compile(params["pattern"])
            except re.error as exc:
                self.add(f"{path}.params.pattern", f"expression régulière invalide ({exc})")
        if rule_type == RuleType.citation_required and isinstance(params.get("pattern"), str):
            try:
                re.compile(params["pattern"])
            except re.error as exc:
                self.add(f"{path}.params.pattern", f"expression régulière invalide ({exc})")
        if rule_type == RuleType.json_schema and isinstance(params.get("schema"), dict):
            try:
                Draft202012Validator.check_schema(params["schema"])
            except SchemaError as exc:
                self.add(f"{path}.params.schema", f"schéma JSON invalide ({exc.message})")

    def tool_mocks(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if not isinstance(value, list):
            self.add("tool_mocks", "liste attendue")
            return []
        result: list[dict[str, Any]] = []
        for i, item in enumerate(value):
            path = f"tool_mocks[{i}]"
            if not isinstance(item, dict):
                self.add(path, "objet {tool, response, match?, error?, latency_ms?} attendu")
                continue
            unknown = set(item) - _MOCK_FIELDS
            if unknown:
                self.add(path, f"champ(s) inconnu(s) : {', '.join(sorted(unknown))}")
            if not isinstance(item.get("tool"), str) or not item["tool"].strip():
                self.add(f"{path}.tool", "nom d'outil requis")
            match = item.get("match")
            if match is not None and not isinstance(match, dict):
                self.add(f"{path}.match", "objet (sous-ensemble des arguments) attendu")
            if item.get("error") is not None and not isinstance(item.get("error"), str):
                self.add(f"{path}.error", "texte attendu")
            latency = item.get("latency_ms")
            if latency is not None and (
                not isinstance(latency, int) or isinstance(latency, bool) or latency < 0
            ):
                self.add(f"{path}.latency_ms", "entier positif attendu")
            result.append(dict(item))
        return result


def _schema_message(error: Any) -> str:
    validator = error.validator
    if validator == "required":
        missing = str(error.message).split("'")
        name = missing[1] if len(missing) > 1 else "?"
        return f"paramètre requis « {name} »"
    if validator == "additionalProperties":
        return f"paramètre non autorisé ({error.message})"
    if validator == "type":
        return f"type invalide (attendu : {error.validator_value})"
    if validator in ("minimum", "exclusiveMinimum"):
        return f"valeur trop petite (minimum {error.validator_value})"
    if validator == "minItems":
        return "liste vide"
    if validator == "minLength":
        return "texte vide"
    if validator == "enum":
        return f"valeur non autorisée (attendu : {', '.join(map(str, error.validator_value))})"
    if validator == "anyOf":
        return "au moins un des paramètres « words » ou « chars » est requis"
    if validator == "pattern":
        return "format invalide"
    return str(error.message)


def normalize_content(
    content: Mapping[str, Any],
    *,
    criteria_catalog: Iterable[str] | None = None,
    error_types: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Validate ``content`` and return its canonical form. Raises :class:`ScenarioValidationError`.

    ``criteria_catalog``: known criterion keys (custom keys prefixed by a dimension are accepted too);
    ``error_types``: known taxonomy codes (``None`` = not checked).
    """
    v = _Validator(
        set(criteria_catalog) if criteria_catalog is not None else None,
        set(error_types) if error_types is not None else None,
    )
    if not isinstance(content, Mapping):
        raise ScenarioValidationError([ValidationIssue("content", "objet attendu")])
    unknown = set(content) - set(CONTENT_FIELDS) - {"changelog"}
    if unknown:
        v.add("content", f"champ(s) inconnu(s) : {', '.join(sorted(unknown))}")
    difficulty = content.get("difficulty") or Difficulty.medium.value
    if difficulty not in {d.value for d in Difficulty}:
        v.add("difficulty", "difficulté attendue : easy, medium, hard ou expert")
    description = content.get("description") or ""
    if not isinstance(description, str):
        v.add("description", "texte attendu")
        description = ""
    expected_behavior = content.get("expected_behavior") or ""
    if not isinstance(expected_behavior, str):
        v.add("expected_behavior", "texte attendu")
        expected_behavior = ""
    dataset_id = content.get("dataset_id")
    if dataset_id is not None and not isinstance(dataset_id, str):
        dataset_id = str(dataset_id)
    normalized = {
        "description": description.strip(),
        "difficulty": str(difficulty),
        "input": v.input(content.get("input")),
        "context": v.context(content.get("context")),
        "constraints": v.constraints(content.get("constraints")),
        "expected_output": content.get("expected_output"),
        "expected_behavior": expected_behavior.strip(),
        "criteria": v.criteria(content.get("criteria")),
        "rules": v.rules(content.get("rules")),
        "tool_mocks": v.tool_mocks(content.get("tool_mocks")),
        "dataset_id": dataset_id or None,
    }
    if v.issues:
        raise ScenarioValidationError(v.issues)
    return normalized


def merge_content(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Variant / new version content: top-level fields of ``overrides`` replace those of ``base``."""
    merged = {k: base.get(k) for k in CONTENT_FIELDS}
    for key, value in overrides.items():
        if key in CONTENT_FIELDS:
            merged[key] = value
    return merged
