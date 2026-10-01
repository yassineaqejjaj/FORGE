"""Deterministic rules (docs/ARCHITECTURE.md §7.2): engine, PII detection, JSON helpers."""

from forge.domain.rules.engine import (
    MISCONFIGURED_PREFIX,
    RULE_HANDLERS,
    criterion_dimension,
    evaluate_rule,
    evaluate_rules,
    rule_criterion_key,
    rule_error_type,
    rule_severity,
    validate_rule,
)
from forge.domain.rules.schemas import RULE_PARAM_SCHEMAS

__all__ = [
    "MISCONFIGURED_PREFIX",
    "RULE_HANDLERS",
    "RULE_PARAM_SCHEMAS",
    "criterion_dimension",
    "evaluate_rule",
    "evaluate_rules",
    "rule_criterion_key",
    "rule_error_type",
    "rule_severity",
    "validate_rule",
]
