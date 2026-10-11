"""Model efficiency (ORION resource optimization): where is a cheaper model as good?

For each group of runs on the same kind of work (a scenario category), models are compared on the share of
runs that passed and on the cost per success. A model is *as good* as the best one when it is not
significantly worse on success rate (one-sided test) and its shortfall stays within a margin; it is worth
recommending when it also costs clearly less per success. Too few runs → no recommendation, never a guess.
Pure functions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from forge.domain.monitoring import WindowStats, worse_proportion_p

ALPHA = 0.05
MIN_RUNS = 20  # scored runs per model before it can be recommended or used as reference
MAX_PASS_RATE_SHORTFALL = 0.05  # tolerated drop in success rate against the best model
MIN_COST_SAVING = 0.15  # relative saving per success that makes a switch worth it


@dataclass(slots=True)
class Recommendation:
    kind: str  # cheaper_equivalent | dominated
    from_model: str
    to_model: str
    pass_rate_from: float
    pass_rate_to: float
    cost_per_success_from: float
    cost_per_success_to: float
    saving: float  # relative: 0.4 = 40 % cheaper per success
    p_value: float | None
    message: str


def _usable(stats: WindowStats) -> bool:
    return stats.n_scored >= MIN_RUNS and stats.pass_rate is not None and stats.cost_per_success is not None


def recommend(models: Mapping[str, WindowStats]) -> list[Recommendation]:
    """Recommendations for one group of work, from the model with the best success rate."""
    usable = {m: s for m, s in models.items() if _usable(s)}
    if len(usable) < 2:
        return []
    best_model = max(usable, key=lambda m: (usable[m].pass_rate or 0.0, -(usable[m].cost_per_success or 0.0)))
    best = usable[best_model]
    found: list[Recommendation] = []
    for model, stats in usable.items():
        if model == best_model or stats.pass_rate is None or best.pass_rate is None:
            continue
        assert stats.cost_per_success is not None and best.cost_per_success is not None
        saving = 1 - stats.cost_per_success / best.cost_per_success
        if saving < MIN_COST_SAVING:
            continue
        shortfall = best.pass_rate - stats.pass_rate
        p = worse_proportion_p(
            stats.n_scored - stats.n_passed, stats.n_scored, best.n_scored - best.n_passed, best.n_scored
        )
        if shortfall > MAX_PASS_RATE_SHORTFALL and (p is None or p < ALPHA):
            continue  # measurably worse: not equivalent
        found.append(
            Recommendation(
                "cheaper_equivalent",
                best_model,
                model,
                best.pass_rate,
                stats.pass_rate,
                best.cost_per_success,
                stats.cost_per_success,
                round(saving, 4),
                None if p is None else round(p, 4),
                f"{model} réussit {stats.pass_rate:.0%} contre {best.pass_rate:.0%} pour {best_model} "
                f"et coûte {saving:.0%} de moins par réussite.",
            )
        )
    # The best model may itself be the cheapest of an equally good pair: the others are then simply dominated.
    for model, stats in usable.items():
        if model == best_model or stats.pass_rate is None or best.pass_rate is None:
            continue
        assert stats.cost_per_success is not None and best.cost_per_success is not None
        if stats.pass_rate > best.pass_rate or stats.cost_per_success <= best.cost_per_success:
            continue
        saving = 1 - best.cost_per_success / stats.cost_per_success
        if saving < MIN_COST_SAVING or any(r.from_model == model for r in found):
            continue
        found.append(
            Recommendation(
                "dominated",
                model,
                best_model,
                stats.pass_rate,
                best.pass_rate,
                stats.cost_per_success,
                best.cost_per_success,
                round(saving, 4),
                None,
                f"{best_model} réussit {best.pass_rate:.0%} contre {stats.pass_rate:.0%} pour {model} "
                f"et coûte {saving:.0%} de moins par réussite.",
            )
        )
    return sorted(found, key=lambda r: -r.saving)
