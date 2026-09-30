"""Content hashes of versioned objects (docs/ARCHITECTURE.md §6.1).

Each function lists exactly the fields that define the object's behaviour. Two versions with the
same hash behave identically; services refuse to create a new version identical to the latest one
(``409 conflict``) and experiments warn when baseline and candidate share a hash.
"""

from __future__ import annotations

import secrets
from typing import Any

from forge.domain.hashing import content_hash

CANARY_PREFIX = "FORGE-CANARY"


def new_canary() -> str:
    """Unique canary string embedded in every scenario version (contamination detection)."""
    return f"{CANARY_PREFIX}-{secrets.token_hex(12)}"


def agent_version_hash(
    *,
    adapter_kind: str,
    endpoint: str | None,
    model: dict[str, Any] | None,
    system_prompt: str,
    tools: list[dict[str, Any]],
    context_config: dict[str, Any],
    memory_config: dict[str, Any],
    orchestration_config: dict[str, Any],
    adapter_config: dict[str, Any],
    budget: dict[str, Any],
    credential_id: str | None,
) -> str:
    return content_hash(
        {
            "adapter_kind": adapter_kind,
            "endpoint": endpoint,
            "model": model,
            "system_prompt": system_prompt,
            "tools": tools,
            "context_config": context_config,
            "memory_config": memory_config,
            "orchestration_config": orchestration_config,
            "adapter_config": adapter_config,
            "budget": budget,
            "credential_id": credential_id,
        }
    )


def model_configuration_hash(data: dict[str, Any]) -> str:
    keys = (
        "provider", "model", "model_version", "temperature", "top_p", "max_tokens", "seed", "params",
        "input_cost_per_mtok", "output_cost_per_mtok",
    )  # fmt: skip
    return content_hash({k: data.get(k) for k in keys})


def prompt_hash(content: str) -> str:
    return content_hash({"content": content})


def tools_hash(tools: list[dict[str, Any]]) -> str:
    return content_hash({"tools": tools})


def scenario_version_hash(
    *,
    description: str,
    difficulty: str,
    input: dict[str, Any],
    context: dict[str, Any],
    constraints: list[str],
    expected_output: Any,
    expected_behavior: str,
    criteria: list[dict[str, Any]],
    rules: list[dict[str, Any]],
    tool_mocks: list[dict[str, Any]],
    dataset_id: str | None,
) -> str:
    return content_hash(
        {
            "description": description,
            "difficulty": difficulty,
            "input": input,
            "context": context,
            "constraints": constraints,
            "expected_output": expected_output,
            "expected_behavior": expected_behavior,
            "criteria": criteria,
            "rules": rules,
            "tool_mocks": tool_mocks,
            "dataset_id": dataset_id,
        }
    )


def judge_hash(
    *,
    provider: str,
    model: str,
    model_version: str | None,
    temperature: float,
    max_tokens: int,
    system_prompt: str,
    rubric_template: str,
    criteria: list[str],
    weight: float,
    base_url: str | None,
    credential_id: str | None,
) -> str:
    return content_hash(
        {
            "provider": provider,
            "model": model,
            "model_version": model_version,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "system_prompt": system_prompt,
            "rubric_template": rubric_template,
            "criteria": sorted(criteria),
            "weight": weight,
            "base_url": base_url,
            "credential_id": credential_id,
        }
    )


def evaluation_config_hash(
    *,
    dimension_weights: dict[str, float],
    criterion_weights: dict[str, float],
    normalization: dict[str, Any],
    gates: list[dict[str, Any]],
    judge_ids: list[str],
    aggregation: dict[str, Any],
    criteria: list[str],
    rules: list[dict[str, Any]],
    use_human_scores: bool,
    pass_threshold: float,
) -> str:
    return content_hash(
        {
            "dimension_weights": dimension_weights,
            "criterion_weights": criterion_weights,
            "normalization": normalization,
            "gates": gates,
            "judge_ids": judge_ids,
            "aggregation": aggregation,
            "criteria": criteria,
            "rules": rules,
            "use_human_scores": use_human_scores,
            "pass_threshold": pass_threshold,
        }
    )
