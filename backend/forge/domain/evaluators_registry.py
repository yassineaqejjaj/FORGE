"""Registry of evaluator kinds (docs/ARCHITECTURE.md §5.2 ``Evaluator`` port).

The evaluation pipeline runs every registered **deterministic** evaluator (rules, metrics…) for each
run, then the judges of the configuration. Adding an evaluator type = implementing
:class:`forge.domain.ports.Evaluator` and registering a factory here::

    class ReadabilityEvaluator:
        kind = EvaluatorKind.metric
        key = "readability"

        async def evaluate(self, ctx: EvaluationContext) -> list[EvaluationResult]: ...

    register_evaluator("readability", lambda: ReadabilityEvaluator(), description="Lisibilité")

Evaluators must explain every score (non-empty ``explanation``) and return normalisable scores
(``scale_min < scale_max``). LLM judges are not registered here: they need clients, credentials,
rate limiting and caching, which the evaluation service provides (``forge.domain.judges.run_judge``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from forge.domain.enums import EvaluatorKind
from forge.domain.ports import Evaluator
from forge.domain.rules import evaluate_rules
from forge.domain.scoring.normalization import metric_results
from forge.domain.types import EvaluationContext, EvaluationResult

EvaluatorFactory = Callable[[], Evaluator]


class RuleEvaluator:
    """Scenario rules + global rules of the configuration (deterministic, free)."""

    kind = EvaluatorKind.rule
    key = "rules"

    async def evaluate(self, ctx: EvaluationContext) -> list[EvaluationResult]:
        return evaluate_rules(ctx, [*ctx.scenario.rules, *ctx.config.rules])


class MetricEvaluator:
    """Cost, tokens and latency normalised by the configuration."""

    kind = EvaluatorKind.metric
    key = "metrics"

    async def evaluate(self, ctx: EvaluationContext) -> list[EvaluationResult]:
        return metric_results(ctx)


@dataclass(frozen=True, slots=True)
class EvaluatorEntry:
    name: str
    factory: EvaluatorFactory
    description: str = ""
    enabled: bool = True


_REGISTRY: dict[str, EvaluatorEntry] = {}


def register_evaluator(
    name: str, factory: EvaluatorFactory, *, description: str = "", replace: bool = False
) -> None:
    if name in _REGISTRY and not replace:
        raise ValueError(f"Evaluator {name!r} already registered")
    _REGISTRY[name] = EvaluatorEntry(name=name, factory=factory, description=description)


def unregister_evaluator(name: str) -> None:
    _REGISTRY.pop(name, None)


def registered_evaluators() -> list[EvaluatorEntry]:
    return list(_REGISTRY.values())


def deterministic_evaluators() -> list[Evaluator]:
    """Fresh instances of every enabled registered evaluator, in registration order."""
    return [entry.factory() for entry in _REGISTRY.values() if entry.enabled]


def validate_results(evaluator: Evaluator, results: list[EvaluationResult]) -> list[EvaluationResult]:
    """Drop results violating the evaluator contract (no explanation, degenerate scale)."""
    valid: list[EvaluationResult] = []
    for result in results:
        if not (result.explanation or "").strip() or result.scale_max <= result.scale_min:
            continue
        valid.append(result)
    return valid


register_evaluator(
    "rules", RuleEvaluator, description="Règles déterministes du scénario et de la configuration"
)
register_evaluator("metrics", MetricEvaluator, description="Métriques de coût, tokens et latence normalisées")
