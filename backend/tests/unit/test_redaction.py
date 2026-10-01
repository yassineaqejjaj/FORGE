"""Private evaluation redaction (docs §3.3) as used by the platform read endpoints."""

from __future__ import annotations

from forge.domain.redaction import (
    PRIVATE_SCENARIO_FIELDS,
    REDACTED_RULE,
    redact_evaluation,
    redact_event,
    redact_rules,
    redact_scenario_content,
)

CONTENT = {
    "description": "secret",
    "input": {"prompt": "secret"},
    "context": {"documents": []},
    "constraints": ["c"],
    "expected_output": "attendu",
    "expected_behavior": "b",
    "tool_mocks": [{"tool": "t"}],
    "canary": "FORGE-CANARY-1",
    "criteria": [{"key": "quality.accuracy"}],
    "rules": [
        {"id": "R1", "type": "contains", "params": {"keywords": ["x"]}},
        {"id": "R2", "type": "regex_absent", "params": {"pattern": "y"}, "hidden": True},
    ],
}


def test_private_content_is_masked_but_criteria_kept() -> None:
    redacted = redact_scenario_content(CONTENT, private=True)
    assert redacted["redacted"] is True
    assert all(redacted[k] is None for k in PRIVATE_SCENARIO_FIELDS)
    assert redacted["criteria"] == CONTENT["criteria"]
    assert all(r["params"] == {} and r["description"] == REDACTED_RULE for r in redacted["rules"])
    assert [r["id"] for r in redacted["rules"]] == ["R1", "R2"]


def test_public_content_hides_canary_and_hidden_rules_only() -> None:
    redacted = redact_scenario_content(CONTENT, private=False)
    assert "canary" not in redacted and redacted["redacted"] is False
    assert redacted["input"] == CONTENT["input"]
    assert redacted["rules"][0]["params"] == {"keywords": ["x"]}
    assert redacted["rules"][1]["params"] == {} and redacted["rules"][1]["hidden"] is True
    assert CONTENT["canary"] == "FORGE-CANARY-1", "input must not be mutated"


def test_redact_rules_and_events_and_evaluations() -> None:
    assert redact_rules([{"id": "R", "type": "json_valid"}], private=False) == [
        {"id": "R", "type": "json_valid"}
    ]
    event = redact_event({"input": "a", "output": "b", "attributes": {"model": "m", "prompt": "secret"}})
    assert event["input"] is None and event["output"] is None and event["attributes"] == {"model": "m"}
    evaluation = redact_evaluation(
        {
            "explanation": "parce que",
            "evidence": [{"excerpt": "x"}],
            "errors": [{"type": "HALLUCINATION", "severity": "high"}],
        }
    )
    assert evaluation["evidence"] == [] and evaluation["errors"][0]["type"] == "HALLUCINATION"
    assert "parce que" not in str(evaluation)
