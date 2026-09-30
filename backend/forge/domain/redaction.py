"""Private evaluation: what non-maintainers may see (docs/ARCHITECTURE.md §3.3).

Results of PRIVATE scenarios stay visible (scores, error types, costs, latencies) but not the full
scenario, the expected output, hidden rules, the agent's input/output, trace payloads, judge
justifications or evidence. Hidden rules (``RuleSpec.hidden``) are masked on every scenario.

All functions are pure and work on JSON-like dicts (API payloads, manifests).
"""

from __future__ import annotations

from typing import Any

REDACTED_TEXT = "Contenu masqué (scénario privé)"
REDACTED_RULE = "Règle masquée"
REDACTED_JUSTIFICATION = "Justification masquée (scénario privé)"

#: Scenario content fields hidden for private scenarios.
PRIVATE_SCENARIO_FIELDS = (
    "input", "context", "constraints", "expected_output", "expected_behavior", "tool_mocks", "canary",
    "description",
)  # fmt: skip
#: Event attributes kept on redacted trace events (structure of the timeline, no payload).
SAFE_EVENT_ATTRIBUTES = frozenset(
    {
        "model",
        "tool",
        "input_tokens",
        "output_tokens",
        "cost",
        "agent",
        "http_status",
        "error_type",
        "documents_count",
    }
)


def is_private(visibility: str | None) -> bool:
    return visibility == "private"


def redact_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": rule.get("id"),
        "type": rule.get("type"),
        "hidden": True,
        "description": REDACTED_RULE,
        "params": {},
        "criterion_key": rule.get("criterion_key"),
        "severity": rule.get("severity"),
    }


def redact_rules(rules: list[dict[str, Any]], *, private: bool) -> list[dict[str, Any]]:
    """Mask hidden rules (always) and every rule's parameters of private scenarios."""
    return [redact_rule(r) if (private or r.get("hidden")) else r for r in rules or []]


def redact_scenario_content(data: dict[str, Any], *, private: bool) -> dict[str, Any]:
    """Scenario version payload (or manifest ``scenario``) as seen by a non-maintainer."""
    result = dict(data)
    if private:
        for key in PRIVATE_SCENARIO_FIELDS:
            if key in result:
                result[key] = None
        result["redacted"] = True
    else:
        result.pop("canary", None)
        result.setdefault("redacted", False)
    if "rules" in result:
        result["rules"] = redact_rules(list(result.get("rules") or []), private=private)
    return result


def redact_event(event: dict[str, Any]) -> dict[str, Any]:
    result = dict(event)
    result["input"] = None
    result["output"] = None
    result["attributes"] = {
        k: v for k, v in dict(event.get("attributes") or {}).items() if k in SAFE_EVENT_ATTRIBUTES
    }
    result["redacted"] = True
    return result


def redact_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    result = dict(evaluation)
    result["explanation"] = REDACTED_JUSTIFICATION
    result["evidence"] = []
    result["raw_response"] = None
    result["errors"] = [
        {"type": e.get("type"), "severity": e.get("severity"), "description": REDACTED_TEXT, "evidence": []}
        for e in evaluation.get("errors") or []
    ]
    result["redacted"] = True
    return result


def redact_error(error: dict[str, Any]) -> dict[str, Any]:
    result = dict(error)
    result["description"] = REDACTED_TEXT
    result["evidence"] = []
    result["redacted"] = True
    return result
