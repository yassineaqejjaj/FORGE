"""Vocabulary schemas (``GET /meta``): enums with French labels, rule types, adapters, capabilities."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel


class EnumOption(ApiModel):
    value: str
    label: str
    description: str | None = None


class RuleTypeOut(ApiModel):
    type: str
    label: str
    description: str
    params_schema: dict[str, Any]
    example: dict[str, Any]
    default_criterion: str
    default_error_type: str | None = None


class AdapterKindOut(ApiModel):
    kind: str
    label: str
    description: str
    requires_model: bool
    requires_endpoint: bool
    credential_kinds: list[str]
    adapter_config: dict[str, Any] = Field(description="Documentation des clés de adapter_config")
    example: dict[str, Any] = Field(description="Exemple de version d'agent (champs principaux)")


class MetaCriterion(ApiModel):
    key: str
    dimension: str
    name: str
    question: str
    scale_min: float
    scale_max: float
    builtin: bool
    judged: bool


class MetaErrorType(ApiModel):
    code: str
    label: str
    description: str
    default_severity: str
    dimension: str
    builtin: bool


class Capabilities(ApiModel):
    llm_judges_configured: bool
    feedback_llm: bool
    orbit_configured: bool


class MetaOut(ApiModel):
    version: str
    enums: dict[str, list[EnumOption]]
    classifications: list[EnumOption]
    categories: list[EnumOption]
    criteria: list[MetaCriterion]
    default_judged_criteria: list[str]
    error_types: list[MetaErrorType]
    rule_types: list[RuleTypeOut]
    adapters: list[AdapterKindOut]
    capabilities: Capabilities
    otlp_endpoint: str
    api_key_header: str
