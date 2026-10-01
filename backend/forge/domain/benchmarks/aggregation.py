"""Benchmark aggregation (docs/ARCHITECTURE.md §9.1): ``RunSummary`` list → ``BenchmarkSummary``.

Conventions:

* a run is **scored** when it is not cancelled and has a composite (failed runs have a composite
  of 0 and count as scored: a crash is a result). Pending / running runs are counted but ignored;
* composites are on the 0–100 scale, dimensions and robustness on 0–1;
* the mean composite of an agent version comes with a seeded 95 % percentile bootstrap interval
  (runs as resampling units); the gap to the leader is tested on per-scenario means (paired
  bootstrap + Wilcoxon), because both versions ran the same scenario versions;
* the ranking uses the **group composite** (mean composite blended with robustness using the
  configuration weight, :func:`forge.domain.benchmarks.robustness.group_composite`);
* the generalisation gap is ``mean(public) − mean(private ∪ fresh)``: a large positive gap
  suggests over-fitting to the visible benchmark.

Everything is pure and deterministic (same runs → same summary).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from forge.domain.benchmarks.labels import (
    DIFFICULTY_ORDER,
    UNKNOWN_KEY,
    agent_name_from_label,
    category_label,
    difficulty_label,
    dimension_label,
    dimension_sort_key,
    model_label,
    visibility_label,
)
from forge.domain.benchmarks.robustness import (
    DEFAULT_ROBUSTNESS_MAX_STD,
    RobustnessResult,
    family_label,
    group_composite,
    robustness,
)
from forge.domain.enums import SEVERITY_RANK, ErrorSeverity, RunStatus, ScenarioVisibility
from forge.domain.stats import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    bootstrap_mean,
    mean,
    median,
    p95,
    paired_bootstrap,
    rate,
    std,
    total,
    wilcoxon_signed_rank,
)
from forge.domain.types import RunSummary

SUMMARY_SCHEMA = "forge.benchmark-summary/v1"
#: Generalisation gap (points) above which over-fitting to public scenarios is flagged.
GENERALISATION_GAP_ALERT = 10.0
#: Significance level of the leader comparison.
ALPHA = 0.05
NO_ERROR_KEY = "none"

GROUP_BY_VALUES: tuple[str, ...] = (
    "agent", "version", "model", "scenario", "category", "difficulty", "visibility", "family",
    "error_type", "date",
)  # fmt: skip


# =====================================================================================================
# Result types
# =====================================================================================================


@dataclass(slots=True)
class ScoreStats:
    """Distribution of composites (0–100) with the bootstrap interval of the mean."""

    n: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None


@dataclass(slots=True)
class MetricStats:
    """Cost (currency units), latency (ms) or tokens of the executed runs."""

    n: int
    mean: float | None = None
    median: float | None = None
    p95: float | None = None
    total: float | None = None


@dataclass(slots=True)
class Generalisation:
    public_mean: float | None
    private_mean: float | None
    fresh_mean: float | None
    hidden_mean: float | None  # private ∪ fresh
    gap: float | None  # public − hidden (points)
    n_public: int
    n_hidden: int
    alert: bool


@dataclass(slots=True)
class LeaderComparison:
    """Paired comparison with the leader of the ranking (per-scenario means)."""

    n_pairs: int
    delta: float | None  # this agent − leader (points)
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    significant: bool | None


@dataclass(slots=True)
class AgentAggregate:
    agent_version_id: str
    agent_id: str
    agent_label: str
    model: str | None
    rank: int
    n_runs: int
    n_scored: int
    n_completed: int
    n_failed: int
    n_cancelled: int
    composite: ScoreStats
    group_composite: float | None
    pass_rate: float | None
    gate_failure_rate: float | None
    error_rate: float | None  # scored runs with ≥ 1 detected error
    dimensions: dict[str, float]
    cost: MetricStats
    latency: MetricStats
    tokens: MetricStats
    errors_by_type: dict[str, int]
    errors_by_severity: dict[str, int]
    robustness: RobustnessResult
    generalisation: Generalisation
    vs_leader: LeaderComparison | None = None


@dataclass(slots=True)
class RankingEntry:
    rank: int
    agent_version_id: str
    agent_label: str
    group_composite: float | None
    composite_mean: float | None
    ci_low: float | None
    ci_high: float | None
    pass_rate: float | None
    delta_to_leader: float | None
    significant_gap: bool | None


@dataclass(slots=True)
class BestEntry:
    dimension: str
    label: str
    agent_version_id: str
    agent_label: str
    value: float


@dataclass(slots=True)
class ScenarioRef:
    scenario_id: str
    scenario_version_id: str
    slug: str
    name: str
    category: str
    difficulty: str
    visibility: str
    family_id: str


@dataclass(slots=True)
class AgentRef:
    agent_version_id: str
    agent_id: str
    label: str
    model: str | None


@dataclass(slots=True)
class MatrixCell:
    scenario_id: str
    scenario_version_id: str
    agent_version_id: str
    n_runs: int
    n_scored: int
    composite_mean: float | None
    composite_std: float | None
    pass_rate: float | None
    gate_failures: int
    error_count: int
    error_types: list[str]
    cost_mean: float | None
    latency_mean: float | None


@dataclass(slots=True)
class Matrix:
    scenarios: list[ScenarioRef]
    agents: list[AgentRef]
    cells: list[MatrixCell]


@dataclass(slots=True)
class GroupRow:
    key: str
    label: str
    n_runs: int
    n_scored: int
    composite_mean: float | None
    composite_ci_low: float | None
    composite_ci_high: float | None
    pass_rate: float | None
    gate_failure_rate: float | None
    cost_mean: float | None
    latency_mean: float | None
    tokens_mean: float | None
    error_count: int
    runs_with_errors: int
    by_agent: dict[str, float | None] = field(default_factory=dict)  # agent_version_id → mean composite


@dataclass(slots=True)
class ErrorTypeRow:
    error_type: str
    count: int
    runs_affected: int
    max_severity: str
    by_severity: dict[str, int]
    by_agent: dict[str, int]  # agent_version_id → occurrences


@dataclass(slots=True)
class Totals:
    n_runs: int
    n_scored: int
    n_completed: int
    n_failed: int
    n_cancelled: int
    n_pending: int
    n_scenarios: int
    n_agents: int
    repetitions: int


@dataclass(slots=True)
class StatisticsInfo:
    confidence: float
    n_resamples: int
    seed: int
    method: str = "percentile_bootstrap"
    significance_test: str = "wilcoxon_signed_rank"
    alpha: float = ALPHA


@dataclass(slots=True)
class BenchmarkSummary:
    schema: str
    totals: Totals
    dimension_weights: dict[str, float]
    statistics: StatisticsInfo
    agents: list[AgentAggregate]
    ranking: list[RankingEntry]
    best_by_dimension: list[BestEntry]
    matrix: Matrix
    by_category: list[GroupRow]
    by_difficulty: list[GroupRow]
    by_model: list[GroupRow]
    by_family: list[GroupRow]
    by_visibility: list[GroupRow]
    by_date: list[GroupRow]
    by_error_type: list[ErrorTypeRow]


# =====================================================================================================
# Helpers
# =====================================================================================================


def is_scored(run: RunSummary) -> bool:
    return run.status != RunStatus.cancelled and run.composite is not None


def _is_executed(run: RunSummary) -> bool:
    return run.status != RunStatus.cancelled


def score_stats(
    values: Sequence[float],
    *,
    with_ci: bool = True,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> ScoreStats:
    if not values:
        return ScoreStats(n=0)
    ci = (
        bootstrap_mean(values, confidence=confidence, n_resamples=n_resamples, seed=seed) if with_ci else None
    )
    return ScoreStats(
        n=len(values),
        mean=mean(values),
        median=median(values),
        std=std(values),
        min=min(values),
        max=max(values),
        ci_low=ci.low if ci else None,
        ci_high=ci.high if ci else None,
    )


def metric_stats(values: Iterable[float | int | None]) -> MetricStats:
    data = [float(v) for v in values if v is not None]
    if not data:
        return MetricStats(n=0)
    return MetricStats(n=len(data), mean=mean(data), median=median(data), p95=p95(data), total=total(data))


def _composites(runs: Iterable[RunSummary]) -> list[float]:
    return [float(r.composite) for r in runs if is_scored(r) and r.composite is not None]


def _dimension_means(runs: Sequence[RunSummary]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        if not is_scored(run):
            continue
        for key, value in run.dimensions.items():
            if value is not None:
                values[key].append(float(value))
    return {
        k: float(sum(v) / len(v)) for k, v in sorted(values.items(), key=lambda kv: dimension_sort_key(kv[0]))
    }


def _per_scenario_means(runs: Iterable[RunSummary]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        if is_scored(run) and run.composite is not None:
            grouped[run.scenario_version_id].append(float(run.composite))
    return {k: sum(v) / len(v) for k, v in grouped.items()}


def _generalisation(scored: Sequence[RunSummary]) -> Generalisation:
    public = [r.composite for r in scored if r.visibility == ScenarioVisibility.public]
    private = [r.composite for r in scored if r.visibility == ScenarioVisibility.private]
    fresh = [r.composite for r in scored if r.visibility == ScenarioVisibility.fresh]
    public_mean = mean(public)
    hidden_mean = mean(private + fresh)
    gap = public_mean - hidden_mean if public_mean is not None and hidden_mean is not None else None
    return Generalisation(
        public_mean=public_mean,
        private_mean=mean(private),
        fresh_mean=mean(fresh),
        hidden_mean=hidden_mean,
        gap=gap,
        n_public=len(public),
        n_hidden=len(private) + len(fresh),
        alert=gap is not None and gap >= GENERALISATION_GAP_ALERT,
    )


def _max_severity(severities: Iterable[str]) -> str:
    best = ErrorSeverity.low
    for value in severities:
        try:
            severity = ErrorSeverity(value)
        except ValueError:
            continue
        if SEVERITY_RANK[severity] > SEVERITY_RANK[best]:
            best = severity
    return best.value


def _sort_by_composite(row: GroupRow) -> tuple[int, float, str]:
    return (row.composite_mean is None, -(row.composite_mean or 0.0), row.label.casefold())


# =====================================================================================================
# Groupings
# =====================================================================================================


def _group_row(
    key: str,
    label: str,
    runs: Sequence[RunSummary],
    *,
    with_ci: bool,
    confidence: float,
    n_resamples: int,
    seed: int,
) -> GroupRow:
    scored = [r for r in runs if is_scored(r)]
    composites = _composites(scored)
    ci = (
        bootstrap_mean(composites, confidence=confidence, n_resamples=n_resamples, seed=seed)
        if with_ci and composites
        else None
    )
    executed = [r for r in runs if _is_executed(r)]
    by_agent_values: dict[str, list[float]] = defaultdict(list)
    for run in scored:
        if run.composite is not None:
            by_agent_values[run.agent_version_id].append(float(run.composite))
    return GroupRow(
        key=key,
        label=label,
        n_runs=len(runs),
        n_scored=len(scored),
        composite_mean=mean(composites),
        composite_ci_low=ci.low if ci else None,
        composite_ci_high=ci.high if ci else None,
        pass_rate=rate(sum(1 for r in scored if r.passed), len(scored)),
        gate_failure_rate=rate(sum(1 for r in scored if r.gate_failed), len(scored)),
        cost_mean=mean(r.cost for r in executed),
        latency_mean=mean(r.latency_ms for r in executed),
        tokens_mean=mean(r.tokens for r in executed),
        error_count=sum(len(r.errors) for r in executed),
        runs_with_errors=sum(1 for r in executed if r.errors),
        by_agent={k: sum(v) / len(v) for k, v in by_agent_values.items()},
    )


def _simple_key(group_by: str) -> Callable[[RunSummary], tuple[str, str]]:
    def by_date(run: RunSummary) -> tuple[str, str]:
        day = run.created_at.date().isoformat() if run.created_at else UNKNOWN_KEY
        return day, day if run.created_at else "Date inconnue"

    keys: dict[str, Callable[[RunSummary], tuple[str, str]]] = {
        "agent": lambda r: (r.agent_id, agent_name_from_label(r.agent_label)),
        "version": lambda r: (r.agent_version_id, r.agent_label),
        "model": lambda r: (r.model or UNKNOWN_KEY, model_label(r.model)),
        "scenario": lambda r: (r.scenario_id, r.scenario_name),
        "category": lambda r: (r.category or UNKNOWN_KEY, category_label(r.category)),
        "difficulty": lambda r: (r.difficulty or UNKNOWN_KEY, difficulty_label(r.difficulty)),
        "visibility": lambda r: (str(r.visibility), visibility_label(str(r.visibility))),
        "family": lambda r: (r.family_id or r.scenario_id, ""),
        "date": by_date,
    }
    return keys[group_by]


def group_runs(
    runs: Sequence[RunSummary],
    group_by: str,
    *,
    with_ci: bool = False,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> list[GroupRow]:
    """Aggregate runs per ``group_by`` (one of :data:`GROUP_BY_VALUES`).

    ``error_type`` puts a run in one group per distinct error type it has (runs without error go
    to the ``none`` group), so the groups overlap by design.
    """
    if group_by not in GROUP_BY_VALUES:
        raise ValueError(f"unknown group_by: {group_by}")
    buckets: dict[str, list[RunSummary]] = defaultdict(list)
    labels: dict[str, str] = {}
    if group_by == "error_type":
        for run in runs:
            types = sorted({t for t, _ in run.errors}) or [NO_ERROR_KEY]
            for error_type in types:
                buckets[error_type].append(run)
                labels[error_type] = "Aucune erreur" if error_type == NO_ERROR_KEY else error_type
    else:
        key_fn = _simple_key(group_by)
        for run in runs:
            key, label = key_fn(run)
            buckets[key].append(run)
            labels.setdefault(key, label)
        if group_by == "family":
            labels = {k: family_label(v) for k, v in buckets.items()}
    rows = [
        _group_row(
            key,
            labels[key],
            members,
            with_ci=with_ci,
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
        )
        for key, members in buckets.items()
    ]
    if group_by in ("agent", "version", "model"):
        rows.sort(key=_sort_by_composite)
    elif group_by == "date":
        rows.sort(key=lambda r: r.key)
    elif group_by == "difficulty":
        rows.sort(key=lambda r: (DIFFICULTY_ORDER.get(r.key, 99), r.key))
    elif group_by == "visibility":
        order = [v.value for v in ScenarioVisibility]
        rows.sort(key=lambda r: order.index(r.key) if r.key in order else 99)
    elif group_by == "error_type":
        rows.sort(key=lambda r: (r.key == NO_ERROR_KEY, -r.error_count, r.key))
    else:
        rows.sort(key=lambda r: (r.label.casefold(), r.key))
    return rows


def error_breakdown(runs: Sequence[RunSummary]) -> list[ErrorTypeRow]:
    """Occurrences of each error type (count, affected runs, severities, per agent version)."""
    counts: Counter[str] = Counter()
    affected: dict[str, set[str]] = defaultdict(set)
    severities: dict[str, Counter[str]] = defaultdict(Counter)
    per_agent: dict[str, Counter[str]] = defaultdict(Counter)
    for run in runs:
        if not _is_executed(run):
            continue
        for error_type, severity in run.errors:
            counts[error_type] += 1
            affected[error_type].add(run.run_id)
            severities[error_type][severity] += 1
            per_agent[error_type][run.agent_version_id] += 1
    rows = [
        ErrorTypeRow(
            error_type=error_type,
            count=count,
            runs_affected=len(affected[error_type]),
            max_severity=_max_severity(severities[error_type]),
            by_severity=dict(sorted(severities[error_type].items())),
            by_agent=dict(per_agent[error_type]),
        )
        for error_type, count in counts.items()
    ]
    rows.sort(key=lambda r: (-r.count, r.error_type))
    return rows


# =====================================================================================================
# Matrix
# =====================================================================================================


def build_matrix(runs: Sequence[RunSummary]) -> Matrix:
    """Scenario × agent version matrix (order of first appearance of scenarios and agents)."""
    scenarios: dict[str, ScenarioRef] = {}
    agents: dict[str, AgentRef] = {}
    cells: dict[tuple[str, str], list[RunSummary]] = defaultdict(list)
    for run in runs:
        scenarios.setdefault(
            run.scenario_version_id,
            ScenarioRef(
                scenario_id=run.scenario_id,
                scenario_version_id=run.scenario_version_id,
                slug=run.scenario_slug,
                name=run.scenario_name,
                category=run.category,
                difficulty=run.difficulty,
                visibility=str(run.visibility),
                family_id=run.family_id,
            ),
        )
        agents.setdefault(
            run.agent_version_id,
            AgentRef(
                agent_version_id=run.agent_version_id,
                agent_id=run.agent_id,
                label=run.agent_label,
                model=run.model,
            ),
        )
        cells[(run.scenario_version_id, run.agent_version_id)].append(run)
    matrix_cells: list[MatrixCell] = []
    for scenario_version_id, scenario in scenarios.items():
        for agent_version_id in agents:
            members = cells.get((scenario_version_id, agent_version_id))
            if not members:
                continue
            scored = [r for r in members if is_scored(r)]
            composites = _composites(scored)
            executed = [r for r in members if _is_executed(r)]
            matrix_cells.append(
                MatrixCell(
                    scenario_id=scenario.scenario_id,
                    scenario_version_id=scenario_version_id,
                    agent_version_id=agent_version_id,
                    n_runs=len(members),
                    n_scored=len(scored),
                    composite_mean=mean(composites),
                    composite_std=std(composites),
                    pass_rate=rate(sum(1 for r in scored if r.passed), len(scored)),
                    gate_failures=sum(1 for r in scored if r.gate_failed),
                    error_count=sum(len(r.errors) for r in executed),
                    error_types=sorted({t for r in executed for t, _ in r.errors}),
                    cost_mean=mean(r.cost for r in executed),
                    latency_mean=mean(r.latency_ms for r in executed),
                )
            )
    return Matrix(scenarios=list(scenarios.values()), agents=list(agents.values()), cells=matrix_cells)


# =====================================================================================================
# Per agent version
# =====================================================================================================


def aggregate_agent(
    runs: Sequence[RunSummary],
    *,
    dimension_weights: Mapping[str, float],
    robustness_max_std: float = DEFAULT_ROBUSTNESS_MAX_STD,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> AgentAggregate:
    """Aggregate the runs of ONE agent version (rank is filled by :func:`aggregate_benchmark`)."""
    if not runs:
        raise ValueError("no runs to aggregate")
    first = runs[0]
    scored = [r for r in runs if is_scored(r)]
    executed = [r for r in runs if _is_executed(r)]
    composite = score_stats(_composites(scored), confidence=confidence, n_resamples=n_resamples, seed=seed)
    robust = robustness(scored, max_std=robustness_max_std)
    dimensions = _dimension_means(scored)
    if robust.value is not None:
        dimensions["robustness"] = robust.value
        dimensions = dict(sorted(dimensions.items(), key=lambda kv: dimension_sort_key(kv[0])))
    errors_by_type: Counter[str] = Counter()
    errors_by_severity: Counter[str] = Counter()
    for run in executed:
        for error_type, severity in run.errors:
            errors_by_type[error_type] += 1
            errors_by_severity[severity] += 1
    models = Counter(r.model for r in runs if r.model)
    return AgentAggregate(
        agent_version_id=first.agent_version_id,
        agent_id=first.agent_id,
        agent_label=first.agent_label,
        model=models.most_common(1)[0][0] if models else None,
        rank=0,
        n_runs=len(runs),
        n_scored=len(scored),
        n_completed=sum(1 for r in runs if r.status == RunStatus.completed),
        n_failed=sum(1 for r in runs if r.status == RunStatus.failed),
        n_cancelled=sum(1 for r in runs if r.status == RunStatus.cancelled),
        composite=composite,
        group_composite=group_composite(composite.mean, robust.value, dimension_weights),
        pass_rate=rate(sum(1 for r in scored if r.passed), len(scored)),
        gate_failure_rate=rate(sum(1 for r in scored if r.gate_failed), len(scored)),
        error_rate=rate(sum(1 for r in scored if r.errors), len(scored)),
        dimensions=dimensions,
        cost=metric_stats(r.cost for r in executed),
        latency=metric_stats(r.latency_ms for r in executed),
        tokens=metric_stats(r.tokens for r in executed),
        errors_by_type=dict(sorted(errors_by_type.items(), key=lambda kv: (-kv[1], kv[0]))),
        errors_by_severity=dict(sorted(errors_by_severity.items())),
        robustness=robust,
        generalisation=_generalisation(scored),
    )


def compare_to_leader(
    runs: Sequence[RunSummary],
    leader_runs: Sequence[RunSummary],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> LeaderComparison:
    """Paired (per scenario version) comparison ``agent − leader``."""
    own = _per_scenario_means(runs)
    lead = _per_scenario_means(leader_runs)
    keys = [k for k in own if k in lead]
    if not keys:
        return LeaderComparison(0, None, None, None, None, None)
    base = [lead[k] for k in keys]
    cand = [own[k] for k in keys]
    boot = paired_bootstrap(base, cand, confidence=confidence, n_resamples=n_resamples, seed=seed)
    p_value = wilcoxon_signed_rank([c - b for b, c in zip(base, cand, strict=True)])
    significant: bool | None = None
    if boot is not None and p_value is not None:
        significant = (boot.high < 0 or boot.low > 0) and p_value < ALPHA
    return LeaderComparison(
        n_pairs=len(keys),
        delta=boot.estimate if boot else None,
        ci_low=boot.low if boot else None,
        ci_high=boot.high if boot else None,
        p_value=p_value,
        significant=significant,
    )


# =====================================================================================================
# Benchmark
# =====================================================================================================


def _totals(runs: Sequence[RunSummary]) -> Totals:
    statuses = Counter(str(r.status) for r in runs)
    terminal = {RunStatus.completed.value, RunStatus.failed.value, RunStatus.cancelled.value}
    return Totals(
        n_runs=len(runs),
        n_scored=sum(1 for r in runs if is_scored(r)),
        n_completed=statuses.get(RunStatus.completed.value, 0),
        n_failed=statuses.get(RunStatus.failed.value, 0),
        n_cancelled=statuses.get(RunStatus.cancelled.value, 0),
        n_pending=sum(c for s, c in statuses.items() if s not in terminal),
        n_scenarios=len({r.scenario_version_id for r in runs}),
        n_agents=len({r.agent_version_id for r in runs}),
        repetitions=(max(r.repetition for r in runs) + 1) if runs else 0,
    )


def _rank_key(agent: AgentAggregate) -> tuple[int, float, float, str]:
    return (
        agent.group_composite is None,
        -(agent.group_composite or 0.0),
        -(agent.composite.mean or 0.0),
        agent.agent_label.casefold(),
    )


def _best_by_dimension(agents: Sequence[AgentAggregate]) -> list[BestEntry]:
    keys = sorted({k for a in agents for k in a.dimensions}, key=dimension_sort_key)
    best: list[BestEntry] = []
    for key in keys:
        candidates = [a for a in agents if key in a.dimensions]
        # Agents are already in ranking order: max() keeps the best-ranked one on ties.
        winner = max(candidates, key=lambda a: a.dimensions[key])
        best.append(
            BestEntry(
                dimension=key,
                label=dimension_label(key),
                agent_version_id=winner.agent_version_id,
                agent_label=winner.agent_label,
                value=winner.dimensions[key],
            )
        )
    return best


def aggregate_benchmark(
    runs: Sequence[RunSummary],
    *,
    dimension_weights: Mapping[str, float],
    robustness_max_std: float = DEFAULT_ROBUSTNESS_MAX_STD,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> BenchmarkSummary:
    """Full benchmark summary (docs §9.1) of the runs of one execution (or any run set)."""
    stats_kwargs: dict[str, Any] = {"confidence": confidence, "n_resamples": n_resamples, "seed": seed}
    per_agent: dict[str, list[RunSummary]] = defaultdict(list)
    for run in runs:
        per_agent[run.agent_version_id].append(run)
    agents = [
        aggregate_agent(
            members,
            dimension_weights=dimension_weights,
            robustness_max_std=robustness_max_std,
            **stats_kwargs,
        )
        for members in per_agent.values()
    ]
    agents.sort(key=_rank_key)
    for index, agent in enumerate(agents, start=1):
        agent.rank = index
    leader = agents[0] if agents and agents[0].composite.n else None
    ranking: list[RankingEntry] = []
    for agent in agents:
        if leader is not None and agent is not leader and agent.composite.n:
            agent.vs_leader = compare_to_leader(
                per_agent[agent.agent_version_id], per_agent[leader.agent_version_id], **stats_kwargs
            )
        delta = (
            agent.group_composite - leader.group_composite
            if leader is not None and agent.group_composite is not None and leader.group_composite is not None
            else None
        )
        ranking.append(
            RankingEntry(
                rank=agent.rank,
                agent_version_id=agent.agent_version_id,
                agent_label=agent.agent_label,
                group_composite=agent.group_composite,
                composite_mean=agent.composite.mean,
                ci_low=agent.composite.ci_low,
                ci_high=agent.composite.ci_high,
                pass_rate=agent.pass_rate,
                delta_to_leader=delta,
                significant_gap=agent.vs_leader.significant if agent.vs_leader else None,
            )
        )
    return BenchmarkSummary(
        schema=SUMMARY_SCHEMA,
        totals=_totals(runs),
        dimension_weights={str(k): float(v) for k, v in dimension_weights.items()},
        statistics=StatisticsInfo(confidence=confidence, n_resamples=n_resamples, seed=seed),
        agents=agents,
        ranking=ranking,
        best_by_dimension=_best_by_dimension(agents),
        matrix=build_matrix(runs),
        by_category=group_runs(runs, "category"),
        by_difficulty=group_runs(runs, "difficulty"),
        by_model=group_runs(runs, "model"),
        by_family=group_runs(runs, "family"),
        by_visibility=group_runs(runs, "visibility"),
        by_date=group_runs(runs, "date"),
        by_error_type=error_breakdown(runs),
    )
