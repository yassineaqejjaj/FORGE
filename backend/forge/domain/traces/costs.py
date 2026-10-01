"""Estimated cost of an execution from the model pricing (docs §8 step 6)."""

from __future__ import annotations

from forge.domain.types import ModelSpec, TokenUsage

MTOK = 1_000_000


def has_pricing(model: ModelSpec | None) -> bool:
    return model is not None and (
        model.input_cost_per_mtok is not None or model.output_cost_per_mtok is not None
    )


def estimate_cost(model: ModelSpec | None, usage: TokenUsage) -> float | None:
    """Tokens × tariff of the ``ModelSpec`` (currency units per 1M tokens); ``None`` without pricing."""
    if model is None or not has_pricing(model):
        return None
    input_price = model.input_cost_per_mtok or 0.0
    output_price = model.output_cost_per_mtok or 0.0
    cost = usage.input_tokens * input_price / MTOK + usage.output_tokens * output_price / MTOK
    return round(cost, 8)


def resolve_cost(
    model: ModelSpec | None, usage: TokenUsage, reported: float | None
) -> tuple[float | None, str | None]:
    """``(cost, source)``: the pricing estimate when available, else the agent-reported cost."""
    estimated = estimate_cost(model, usage) if usage.total_tokens > 0 else None
    if estimated is not None:
        return estimated, "pricing"
    if reported is not None:
        return round(max(0.0, float(reported)), 8), "agent"
    return None, None
