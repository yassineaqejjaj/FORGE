"""Robustness (docs/ARCHITECTURE.md §9.2) and group composite.

Robustness only exists for *groups* of runs: for one agent version and one scenario family
(the root scenario, its variants and every repetition), the dispersion of the composites measures
how stable the agent is when the task varies slightly or is simply repeated.

* ``σ_f`` = sample standard deviation (``ddof=1``) of the family's composites on the 0–1 scale.
  Failed runs count with their composite of 0: an agent that sometimes crashes is not robust.
* ``robustness_f = 1 − min(1, σ_f / robustness_max_std)`` (``robustness_max_std`` comes from the
  evaluation configuration, default 0.25).
* agent robustness = mean of the family robustness weighted by the number of runs of each family.
  Families with fewer than two scored runs carry no dispersion information and are skipped;
  robustness is ``None`` when no family qualifies (single run per scenario, no variants).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from forge.domain.enums import Dimension
from forge.domain.stats import std
from forge.domain.types import RunSummary

DEFAULT_ROBUSTNESS_MAX_STD = 0.25


@dataclass(slots=True)
class FamilyRobustness:
    family_id: str
    label: str
    n_runs: int
    n_scenarios: int
    std: float  # 0–1 scale
    robustness: float  # 0–1


@dataclass(slots=True)
class RobustnessResult:
    value: float | None  # 0–1
    n_families: int
    families: list[FamilyRobustness] = field(default_factory=list)


def family_label(runs: Sequence[RunSummary]) -> str:
    """Name of the family's root scenario when present, else of its first scenario."""
    for run in runs:
        if run.scenario_id == run.family_id:
            return run.scenario_name
    return runs[0].scenario_name if runs else ""


def robustness(
    runs: Sequence[RunSummary], *, max_std: float = DEFAULT_ROBUSTNESS_MAX_STD
) -> RobustnessResult:
    """Robustness of ONE agent version over its scored runs (composite not ``None``)."""
    if max_std <= 0:
        raise ValueError("robustness_max_std must be > 0")
    by_family: dict[str, list[RunSummary]] = defaultdict(list)
    for run in runs:
        if run.composite is not None:
            by_family[run.family_id or run.scenario_id].append(run)
    families: list[FamilyRobustness] = []
    for family_id, members in by_family.items():
        sigma = std([m.composite / 100.0 for m in members if m.composite is not None])
        if sigma is None:
            continue
        families.append(
            FamilyRobustness(
                family_id=family_id,
                label=family_label(members),
                n_runs=len(members),
                n_scenarios=len({m.scenario_id for m in members}),
                std=sigma,
                robustness=1.0 - min(1.0, sigma / max_std),
            )
        )
    families.sort(key=lambda f: (f.robustness, f.label))
    weight = sum(f.n_runs for f in families)
    value = sum(f.robustness * f.n_runs for f in families) / weight if weight else None
    return RobustnessResult(value=value, n_families=len(families), families=families)


def robustness_share(dimension_weights: Mapping[str, float]) -> float:
    """Share of the robustness weight among the positive configured dimension weights."""
    positive = {k: float(v) for k, v in dimension_weights.items() if float(v) > 0}
    total = sum(positive.values())
    if total <= 0:
        return 0.0
    return positive.get(Dimension.robustness.value, 0.0) / total


def group_composite(
    composite_mean: float | None, robustness_value: float | None, dimension_weights: Mapping[str, float]
) -> float | None:
    """Composite of a group of runs (0–100) including robustness with its configured weight.

    Run composites already combine every other dimension (renormalised over the available ones,
    gates applied), so the group composite blends their mean with robustness:
    ``G = (1 − s)·mean(composite) + s·100·robustness`` where ``s = w_robustness / Σ w_d``.
    Without robustness (not measurable) the group composite is the mean run composite.
    """
    if composite_mean is None:
        return None
    share = robustness_share(dimension_weights)
    if robustness_value is None or share <= 0:
        return composite_mean
    return (1.0 - share) * composite_mean + share * 100.0 * robustness_value
