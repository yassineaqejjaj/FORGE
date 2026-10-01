"""Which criteria each judge evaluates, and bias warnings (docs/ARCHITECTURE.md §7.1 step 5, §7.3)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from forge.domain.defaults import DEFAULT_JUDGED_CRITERIA
from forge.domain.enums import Dimension
from forge.domain.types import AgentSpec, CriterionSpec, JudgeSpec, ScenarioSpec, ScoreConfig

#: Dimensions never submitted to judges (measured, or group-level).
NON_JUDGED_DIMENSIONS: frozenset[Dimension] = frozenset(
    {Dimension.cost, Dimension.latency, Dimension.robustness}
)

_FAMILIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic", re.compile(r"claude|anthropic", re.I)),
    ("openai", re.compile(r"\bgpt|^o\d|openai|chatgpt", re.I)),
    ("google", re.compile(r"gemini|gemma|palm|bison", re.I)),
    ("mistral", re.compile(r"mistral|mixtral|codestral|magistral", re.I)),
    ("meta", re.compile(r"llama", re.I)),
    ("alibaba", re.compile(r"qwen", re.I)),
    ("deepseek", re.compile(r"deepseek", re.I)),
)


def judged_criteria(
    scenario: ScenarioSpec, config: ScoreConfig, catalog: Mapping[str, CriterionSpec]
) -> list[CriterionSpec]:
    """Scenario criteria (or the defaults) + configuration criteria, judged dimensions only, stable order."""
    base = list(scenario.criteria) or [catalog[k] for k in DEFAULT_JUDGED_CRITERIA if k in catalog]
    ordered: dict[str, CriterionSpec] = {}
    for criterion in [*base, *config.criteria]:
        if Dimension(criterion.dimension) in NON_JUDGED_DIMENSIONS:
            continue
        ordered.setdefault(criterion.key, criterion)
    return list(ordered.values())


def criteria_for_judge(judge: JudgeSpec, criteria: Sequence[CriterionSpec]) -> list[CriterionSpec]:
    if not judge.criteria:
        return list(criteria)
    allowed = set(judge.criteria)
    return [c for c in criteria if c.key in allowed]


def model_family(model: str | None, provider: str | None = None) -> str | None:
    text = f"{provider or ''} {model or ''}".strip()
    if not text:
        return None
    for family, pattern in _FAMILIES:
        if pattern.search(model or "") or (provider and pattern.search(provider)):
            return family
    return None


def self_preference_warning(judge: JudgeSpec, agent: AgentSpec) -> str | None:
    """Warning when the judge and the evaluated agent belong to the same model family."""
    if str(judge.provider) == "heuristic" or agent.model is None:
        return None
    judge_family = model_family(judge.model)
    agent_family = model_family(agent.model.model, agent.model.provider)
    if judge_family and judge_family == agent_family:
        return (
            f"Biais d'auto-préférence possible : le juge {judge.ref} ({judge.model}) et l'agent évalué "
            f"({agent.model.model}) appartiennent à la même famille de modèles ({judge_family})."
        )
    return None
