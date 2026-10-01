"""Public list prices of common models (currency units — USD — per 1M tokens), docs §7.3.

Lookup is by exact id first, then by the longest known prefix (``gpt-4.1-mini-2025-04-14`` →
``gpt-4.1-mini``, ``claude-haiku-4-5-20251001`` → ``claude-haiku-4-5``). Unknown models → ``None``
(the judge cost is then reported as unknown, never guessed).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


MODEL_PRICES: dict[str, ModelPrice] = {
    # Anthropic
    "claude-fable-5-1": ModelPrice(10.0, 50.0),
    "claude-fable-5": ModelPrice(10.0, 50.0),
    "claude-opus-5-5": ModelPrice(4.0, 20.0),
    "claude-opus-5": ModelPrice(5.0, 25.0),
    "claude-opus-4-8": ModelPrice(5.0, 25.0),
    "claude-opus-4-7": ModelPrice(5.0, 25.0),
    "claude-opus-4-6": ModelPrice(5.0, 25.0),
    "claude-opus-4-5": ModelPrice(5.0, 25.0),
    "claude-sonnet-5-5": ModelPrice(2.0, 10.0),
    "claude-sonnet-5": ModelPrice(2.0, 10.0),
    "claude-sonnet-4-6": ModelPrice(3.0, 15.0),
    "claude-sonnet-4-5": ModelPrice(3.0, 15.0),
    "claude-sonnet-4": ModelPrice(3.0, 15.0),
    "claude-haiku-4-5": ModelPrice(1.0, 5.0),
    "claude-3-5-haiku": ModelPrice(0.8, 4.0),
    # OpenAI
    "gpt-5": ModelPrice(1.25, 10.0),
    "gpt-5-mini": ModelPrice(0.25, 2.0),
    "gpt-5-nano": ModelPrice(0.05, 0.40),
    "gpt-4.1": ModelPrice(2.0, 8.0),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    "gpt-4.1-nano": ModelPrice(0.10, 0.40),
    "gpt-4o": ModelPrice(2.50, 10.0),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "o3": ModelPrice(2.0, 8.0),
    "o4-mini": ModelPrice(1.10, 4.40),
}

_BY_LENGTH = sorted(MODEL_PRICES, key=len, reverse=True)


def price_for(model: str | None) -> ModelPrice | None:
    if not model:
        return None
    name = model.strip().lower()
    if "/" in name:  # "openai/gpt-4.1", "anthropic/claude-…" (routers / proxies)
        name = name.rsplit("/", 1)[-1]
    if name in MODEL_PRICES:
        return MODEL_PRICES[name]
    for known in _BY_LENGTH:
        if name.startswith(known) and (len(name) == len(known) or name[len(known)] in "-@:."):
            # Avoid "gpt-5" matching "gpt-5-mini…": longer prefixes are tried first.
            return MODEL_PRICES[known]
    return None


def estimate_cost(model: str | None, input_tokens: int, output_tokens: int) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    return round((input_tokens * price.input_per_mtok + output_tokens * price.output_per_mtok) / 1_000_000, 8)
