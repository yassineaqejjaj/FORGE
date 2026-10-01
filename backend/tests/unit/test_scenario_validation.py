"""Scenario content validation (rule params per §7.2, criteria keys, tool mocks, input)."""

from __future__ import annotations

import pytest

from forge.domain.defaults import CRITERIA_BY_KEY, RULE_DEFAULTS
from forge.domain.enums import RuleType
from forge.domain.scenarios.rule_schemas import RULE_PARAM_SCHEMAS, RULE_TYPE_INFO, rule_type_catalog
from forge.domain.scenarios.validation import (
    ScenarioValidationError,
    is_valid_criterion_key,
    merge_content,
    normalize_content,
)
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES

CATALOG = set(CRITERIA_BY_KEY)
ERRORS = set(BUILTIN_ERROR_TYPES)


def _validate(**content):
    content.setdefault("input", {"prompt": "Rédige un PRD"})
    return normalize_content(content, criteria_catalog=CATALOG, error_types=ERRORS)


def _issues(**content) -> list[str]:
    with pytest.raises(ScenarioValidationError) as exc_info:
        _validate(**content)
    return [f"{i.path} {i.message}" for i in exc_info.value.issues]


def test_minimal_content_is_normalized_with_defaults() -> None:
    content = _validate()
    assert content["difficulty"] == "medium"
    assert content["rules"] == [] and content["criteria"] == [] and content["tool_mocks"] == []
    assert content["context"] == {} and content["constraints"] == []
    assert set(content) == {
        "description", "difficulty", "input", "context", "constraints", "expected_output",
        "expected_behavior", "criteria", "rules", "tool_mocks", "dataset_id",
    }  # fmt: skip


def test_input_requires_prompt_or_messages() -> None:
    assert any("prompt" in i for i in _issues(input={}))
    assert any("prompt" in i for i in _issues(input={"prompt": "   "}))
    assert _validate(input={"messages": [{"role": "user", "content": "Bonjour"}]})["input"]["messages"]
    assert any("role" in i for i in _issues(input={"messages": [{"role": "robot", "content": "x"}]}))


def test_rule_ids_are_filled_and_unique() -> None:
    content = _validate(
        rules=[
            {"type": "json_valid"},
            {"id": "R1", "type": "contains", "params": {"keywords": ["PRD"]}},
            {"type": "no_canary"},
        ]
    )
    ids = [r["id"] for r in content["rules"]]
    assert ids[1] == "R1" and len(set(ids)) == 3 and all(ids)
    assert any(
        "dupliqué" in i
        for i in _issues(rules=[{"id": "A", "type": "json_valid"}, {"id": "A", "type": "json_valid"}])
    )


@pytest.mark.parametrize(
    ("rule", "fragment"),
    [
        ({"type": "unknown_rule"}, "type de règle inconnu"),
        ({"type": "contains", "params": {}}, "keywords"),
        ({"type": "contains", "params": {"keywords": []}}, "liste vide"),
        ({"type": "contains", "params": {"keywords": ["a"], "mode": "some"}}, "non autorisée"),
        ({"type": "contains", "params": {"keywords": ["a"], "colour": "red"}}, "non autorisé"),
        ({"type": "regex_match", "params": {"pattern": "("}}, "expression régulière invalide"),
        ({"type": "regex_match", "params": {"pattern": "a", "flags": "x"}}, "format invalide"),
        ({"type": "json_schema", "params": {"schema": {"type": 12}}}, "schéma JSON invalide"),
        ({"type": "max_length", "params": {}}, "words"),
        ({"type": "max_latency", "params": {"ms": 0}}, "trop petite"),
        ({"type": "tool_called", "params": {"tool": ""}}, "texte vide"),
        ({"type": "expected_value", "params": {"path": "a"}}, "value"),
        ({"type": "no_pii", "params": {"types": ["SSN"]}}, "non autorisée"),
        ({"type": "json_valid", "severity": "fatal"}, "gravité"),
        ({"type": "json_valid", "error_type": "NOT_A_TYPE"}, "type d'erreur inconnu"),
        ({"type": "json_valid", "criterion_key": "nope.x"}, "critère inconnu"),
        ({"type": "json_valid", "weight": 0}, "poids"),
        ({"type": "json_valid", "foo": 1}, "champ(s) inconnu(s)"),
    ],
)
def test_invalid_rules_are_reported(rule: dict, fragment: str) -> None:
    issues = _issues(rules=[rule])
    assert any(fragment in i for i in issues), issues


@pytest.mark.parametrize("rule_type", list(RuleType))
def test_every_rule_type_has_schema_and_valid_example(rule_type: RuleType) -> None:
    assert rule_type in RULE_PARAM_SCHEMAS and rule_type in RULE_TYPE_INFO
    example = RULE_TYPE_INFO[rule_type].example
    content = _validate(rules=[{"type": rule_type.value, "params": example}])
    assert content["rules"][0]["params"] == example


def test_rule_catalog_exposes_defaults() -> None:
    catalog = {r["type"]: r for r in rule_type_catalog()}
    assert set(catalog) == {t.value for t in RuleType}
    assert catalog["no_canary"]["default_error_type"] == "CONTAMINATION"
    assert catalog["contains"]["default_criterion"] == RULE_DEFAULTS[RuleType.contains][0]
    assert catalog["contains"]["params_schema"]["required"] == ["keywords"]


def test_criteria_keys_catalog_or_dimension_prefixed() -> None:
    content = _validate(criteria=["quality.accuracy", {"key": "ux.tone_of_voice", "weight": 2}])
    assert [c["key"] for c in content["criteria"]] == ["quality.accuracy", "ux.tone_of_voice"]
    assert is_valid_criterion_key("safety.custom_rule")
    assert not is_valid_criterion_key("style.tone")
    assert any("critère inconnu" in i for i in _issues(criteria=[{"key": "style.tone"}]))
    assert any("dupliqué" in i for i in _issues(criteria=["quality.accuracy", "quality.accuracy"]))
    assert any(
        "scale_min" in i
        for i in _issues(criteria=[{"key": "quality.accuracy", "scale_min": 5, "scale_max": 1}])
    )


def test_tool_mocks_and_context_documents() -> None:
    content = _validate(
        tool_mocks=[{"tool": "search", "response": {"hits": 2}, "match": {"q": "export"}, "latency_ms": 10}],
        context={"documents": [{"id": "D1", "title": "Spec", "content": "…"}]},
    )
    assert content["tool_mocks"][0]["tool"] == "search"
    assert any("tool" in i for i in _issues(tool_mocks=[{"response": 1}]))
    assert any("latency_ms" in i for i in _issues(tool_mocks=[{"tool": "x", "latency_ms": -1}]))
    assert any(
        "dupliqué" in i
        for i in _issues(context={"documents": [{"id": "a", "content": "x"}, {"id": "a", "content": "y"}]})
    )


def test_unknown_fields_and_bad_difficulty() -> None:
    issues = _issues(difficulty="impossible", colour="red")
    assert any("difficulté" in i for i in issues) and any("inconnu" in i for i in issues)


def test_all_issues_are_reported_at_once() -> None:
    with pytest.raises(ScenarioValidationError) as exc_info:
        normalize_content(
            {"input": {}, "rules": [{"type": "nope"}], "criteria": ["bad"]}, criteria_catalog=CATALOG
        )
    assert len(exc_info.value.issues) >= 3
    assert str(exc_info.value).startswith("Scénario invalide")


def test_merge_content_replaces_top_level_fields() -> None:
    base = _validate(constraints=["court"], expected_output="A")
    merged = merge_content(base, {"expected_output": "B", "unknown": 1})
    assert merged["expected_output"] == "B" and merged["constraints"] == ["court"] and "unknown" not in merged
