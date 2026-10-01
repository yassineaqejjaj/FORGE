"""Paired baseline vs candidate comparison (docs/ARCHITECTURE.md §9.3).

Statistical design:

* **Unit of analysis = scenario version.** Both arms ran the same scenario versions; the K
  repetitions of a scenario are averaged per arm first, then compared pairwise. Repetitions
  reduce the noise of each scenario mean but are *not* independent units: treating them as
  separate pairs would overstate the evidence. Scenarios without a scored run in both arms are
  reported as ``unpaired`` and excluded from the tests.
* **Composite and dimensions** are compared on the 0–100 scale (dimensions ×100): means of the
  paired scenario means, delta in points and in % of the baseline, seeded paired percentile
  bootstrap interval (10 000 resamples) of the mean difference, two-sided Wilcoxon signed-rank
  p-value.
* **Verdict**: ``equivalent`` when ``|delta| < 2`` points and the interval lies within ±5 points
  (practical equivalence wins over a statistically significant but negligible change);
  ``better`` / ``worse`` when the interval excludes 0 *and* ``p < 0.05``; ``inconclusive``
  otherwise (including fewer than 2 pairs).
* **Scenario regressions**: ``σ_noise`` is the pooled standard deviation of the repetitions of
  that scenario (both arms); with a single repetition it cannot be measured and defaults to 5
  points. A scenario regresses when ``delta ≤ −max(5, 2σ)``; a *new* gate failure or a *new*
  critical error is always reported as a critical regression, even within the noise band, because
  it is a hard failure rather than a score fluctuation. Severity: ``critical`` (new gate failure,
  new critical error or ``delta ≤ −15``), ``major`` (``delta ≤ −10``), otherwise ``minor``.
  Improvements are symmetric.
* **Cost, latency, tokens**: means of the paired scenario means; a decrease is a gain.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from forge.domain.benchmarks.aggregation import is_scored
from forge.domain.benchmarks.labels import RESOURCE_LABELS, dimension_label, dimension_sort_key
from forge.domain.benchmarks.robustness import DEFAULT_ROBUSTNESS_MAX_STD, robustness
from forge.domain.enums import (
    GROUP_DIMENSIONS,
    SEVERITY_RANK,
    ErrorSeverity,
    ExperimentArm,
    RegressionSeverity,
    RunStatus,
    Verdict,
)
from forge.domain.stats import (
    DEFAULT_CONFIDENCE,
    DEFAULT_RESAMPLES,
    DEFAULT_SEED,
    mean,
    paired_bootstrap,
    pooled_std,
    rate,
    wilcoxon_signed_rank,
)
from forge.domain.stats.formatting import fr_number
from forge.domain.types import RunSummary

COMPARISON_SCHEMA = "forge.experiment-comparison/v1"

ALPHA = 0.05
MIN_PAIRS = 2
EQUIVALENCE_DELTA = 2.0  # points
EQUIVALENCE_MARGIN = 5.0  # points: interval must lie within ±margin
DEFAULT_NOISE_STD = 5.0  # points, when repetitions cannot measure the noise (K = 1)
MIN_SCENARIO_DELTA = 5.0  # points: floor of the regression threshold
MAJOR_DELTA = 10.0
CRITICAL_DELTA = 15.0
#: Relative change of cost / latency / tokens considered stable (±5 %).
RESOURCE_STABLE_BAND = 0.05
#: Change of error occurrences per run considered meaningful.
ERROR_RATE_CHANGE = 0.05


# =====================================================================================================
# Result types
# =====================================================================================================


@dataclass(slots=True)
class MetricComparison:
    key: str  # "composite" or a dimension
    label: str
    n_pairs: int
    baseline_mean: float | None  # points (0–100)
    candidate_mean: float | None
    delta: float | None  # candidate − baseline (points)
    delta_pct: float | None  # % of the baseline mean
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    prob_improvement: float | None  # share of bootstrap means > 0
    verdict: Verdict


@dataclass(slots=True)
class ResourceComparison:
    key: str  # cost | latency | tokens
    label: str
    unit: str
    n_pairs: int
    baseline_mean: float | None
    candidate_mean: float | None
    delta: float | None
    relative_change: float | None  # (candidate − baseline) / baseline
    p_value: float | None
    assessment: str  # gain | loss | stable | unknown (lower is better)


@dataclass(slots=True)
class ScenarioChange:
    scenario_id: str
    scenario_version_id: str
    slug: str
    name: str
    category: str
    difficulty: str
    visibility: str
    n_baseline: int
    n_candidate: int
    baseline_mean: float | None
    candidate_mean: float | None
    delta: float | None
    noise_std: float
    noise_estimated: bool
    threshold: float
    status: str  # regression | improvement | stable | unpaired
    severity: RegressionSeverity | None = None
    baseline_gate_failures: int = 0
    candidate_gate_failures: int = 0
    new_critical_errors: list[str] = field(default_factory=list)
    resolved_critical_errors: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ErrorChange:
    error_type: str
    baseline_count: int
    candidate_count: int
    baseline_rate: float | None  # occurrences per executed run
    candidate_rate: float | None
    delta_rate: float | None
    max_severity: str
    change: str  # appeared | disappeared | increased | decreased | stable


@dataclass(slots=True)
class ErrorsComparison:
    appeared: list[str]
    disappeared: list[str]
    changes: list[ErrorChange]
    baseline_error_rate: float | None  # share of executed runs with ≥ 1 error
    candidate_error_rate: float | None


@dataclass(slots=True)
class ArmSummary:
    arm: ExperimentArm
    agent_version_id: str | None
    agent_label: str
    n_runs: int
    n_scored: int
    n_failed: int
    n_cancelled: int
    composite_mean: float | None
    pass_rate: float | None
    gate_failure_rate: float | None
    error_rate: float | None
    robustness: float | None


@dataclass(slots=True)
class RobustnessComparison:
    baseline: float | None
    candidate: float | None
    delta: float | None  # points (×100)


@dataclass(slots=True)
class NoiseInfo:
    pooled_std: float | None  # points, over every (scenario, arm) cell with repetitions
    dof: int
    repetitions: int
    default_std: float = DEFAULT_NOISE_STD


@dataclass(slots=True)
class RecommendationResult:
    recommendation: str
    label: str
    confidence: str  # high | medium | low
    confidence_label: str
    summary: str
    reasons: list[str]


@dataclass(slots=True)
class ComparisonStatistics:
    confidence: float
    n_resamples: int
    seed: int
    alpha: float = ALPHA
    method: str = "paired_percentile_bootstrap"
    significance_test: str = "wilcoxon_signed_rank"
    unit: str = "scenario_version"
    equivalence_delta: float = EQUIVALENCE_DELTA
    equivalence_margin: float = EQUIVALENCE_MARGIN
    min_regression_delta: float = MIN_SCENARIO_DELTA


@dataclass(slots=True)
class ExperimentComparison:
    schema: str
    baseline: ArmSummary
    candidate: ArmSummary
    n_pairs: int
    n_unpaired: int
    composite: MetricComparison
    dimensions: list[MetricComparison]
    resources: list[ResourceComparison]
    scenarios: list[ScenarioChange]
    regressions: list[ScenarioChange]
    improvements: list[ScenarioChange]
    errors: ErrorsComparison
    robustness: RobustnessComparison
    noise: NoiseInfo
    recommendation: RecommendationResult
    warnings: list[str]
    statistics: ComparisonStatistics


# =====================================================================================================
# Metric comparison
# =====================================================================================================


def metric_verdict(
    delta: float | None, ci_low: float | None, ci_high: float | None, p_value: float | None, n_pairs: int
) -> Verdict:
    """Verdict of a paired comparison on the 0–100 scale (see module docstring)."""
    if delta is None or ci_low is None or ci_high is None or n_pairs < MIN_PAIRS:
        return Verdict.inconclusive
    if abs(delta) < EQUIVALENCE_DELTA and ci_low >= -EQUIVALENCE_MARGIN and ci_high <= EQUIVALENCE_MARGIN:
        return Verdict.equivalent
    significant = p_value is not None and p_value < ALPHA
    if significant and ci_low > 0:
        return Verdict.better
    if significant and ci_high < 0:
        return Verdict.worse
    return Verdict.inconclusive


def compare_metric(
    key: str,
    label: str,
    baseline: dict[str, float],
    candidate: dict[str, float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> MetricComparison:
    """Paired comparison of per-unit values (``unit key → value in points``)."""
    keys = sorted(k for k in baseline if k in candidate)
    base = [baseline[k] for k in keys]
    cand = [candidate[k] for k in keys]
    boot = paired_bootstrap(base, cand, confidence=confidence, n_resamples=n_resamples, seed=seed)
    p_value = wilcoxon_signed_rank([c - b for b, c in zip(base, cand, strict=True)])
    base_mean, cand_mean = mean(base), mean(cand)
    delta = boot.estimate if boot else None
    delta_pct = delta / base_mean * 100.0 if delta is not None and base_mean else None
    ci_low, ci_high = (boot.low, boot.high) if boot else (None, None)
    return MetricComparison(
        key=key,
        label=label,
        n_pairs=len(keys),
        baseline_mean=base_mean,
        candidate_mean=cand_mean,
        delta=delta,
        delta_pct=delta_pct,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        prob_improvement=boot.prob_positive if boot else None,
        verdict=metric_verdict(delta, ci_low, ci_high, p_value, len(keys)),
    )


def _per_scenario(
    runs: Sequence[RunSummary], value: Callable[[RunSummary], float | None], *, scored_only: bool = True
) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        if scored_only and not is_scored(run):
            continue
        if run.status == RunStatus.cancelled:
            continue
        v = value(run)
        if v is not None:
            grouped[run.scenario_version_id].append(float(v))
    return {k: sum(v) / len(v) for k, v in grouped.items() if v}


def _composite_points(run: RunSummary) -> float | None:
    return float(run.composite) if run.composite is not None else None


def _dimension_points(key: str) -> Callable[[RunSummary], float | None]:
    def getter(run: RunSummary) -> float | None:
        value = run.dimensions.get(key)
        return float(value) * 100.0 if value is not None else None

    return getter


def _resource(
    key: str,
    unit: str,
    baseline: Sequence[RunSummary],
    candidate: Sequence[RunSummary],
    value: Callable[[RunSummary], float | None],
) -> ResourceComparison:
    base = _per_scenario(baseline, value, scored_only=False)
    cand = _per_scenario(candidate, value, scored_only=False)
    keys = sorted(k for k in base if k in cand)
    base_values = [base[k] for k in keys]
    cand_values = [cand[k] for k in keys]
    base_mean, cand_mean = mean(base_values), mean(cand_values)
    delta = cand_mean - base_mean if base_mean is not None and cand_mean is not None else None
    relative = delta / base_mean if delta is not None and base_mean else None
    if relative is None:
        assessment = "unknown" if delta is None or delta != 0 else "stable"
    elif abs(relative) < RESOURCE_STABLE_BAND:
        assessment = "stable"
    else:
        assessment = "gain" if relative < 0 else "loss"
    return ResourceComparison(
        key=key,
        label=RESOURCE_LABELS.get(key, key),
        unit=unit,
        n_pairs=len(keys),
        baseline_mean=base_mean,
        candidate_mean=cand_mean,
        delta=delta,
        relative_change=relative,
        p_value=wilcoxon_signed_rank([c - b for b, c in zip(base_values, cand_values, strict=True)]),
        assessment=assessment,
    )


# =====================================================================================================
# Scenario regressions
# =====================================================================================================


def _critical_types(runs: Sequence[RunSummary]) -> set[str]:
    return {t for r in runs for t, s in r.errors if s == ErrorSeverity.critical}


def _magnitude(change_points: float, *, hard_failure: bool) -> RegressionSeverity:
    """Severity of a change of ``change_points`` (positive = size of the drop or of the gain)."""
    if hard_failure or change_points >= CRITICAL_DELTA:
        return RegressionSeverity.critical
    if change_points >= MAJOR_DELTA:
        return RegressionSeverity.major
    return RegressionSeverity.minor


def scenario_change(
    baseline: Sequence[RunSummary],
    candidate: Sequence[RunSummary],
    *,
    default_noise: float = DEFAULT_NOISE_STD,
) -> ScenarioChange:
    """Classify the change of ONE scenario version (runs of both arms, any status)."""
    ref = (baseline or candidate)[0]
    base_scored = [r for r in baseline if is_scored(r)]
    cand_scored = [r for r in candidate if is_scored(r)]
    base_values = [float(r.composite) for r in base_scored if r.composite is not None]
    cand_values = [float(r.composite) for r in cand_scored if r.composite is not None]
    noise, dof = pooled_std([base_values, cand_values])
    noise_estimated = dof > 0 and noise is not None
    sigma = float(noise) if noise_estimated and noise is not None else default_noise
    threshold = max(MIN_SCENARIO_DELTA, 2.0 * sigma)
    base_mean, cand_mean = mean(base_values), mean(cand_values)
    base_gate = sum(1 for r in base_scored if r.gate_failed)
    cand_gate = sum(1 for r in cand_scored if r.gate_failed)
    base_critical, cand_critical = _critical_types(baseline), _critical_types(candidate)
    change = ScenarioChange(
        scenario_id=ref.scenario_id,
        scenario_version_id=ref.scenario_version_id,
        slug=ref.scenario_slug,
        name=ref.scenario_name,
        category=ref.category,
        difficulty=ref.difficulty,
        visibility=str(ref.visibility),
        n_baseline=len(base_values),
        n_candidate=len(cand_values),
        baseline_mean=base_mean,
        candidate_mean=cand_mean,
        delta=None,
        noise_std=sigma,
        noise_estimated=noise_estimated,
        threshold=threshold,
        status="unpaired",
        baseline_gate_failures=base_gate,
        candidate_gate_failures=cand_gate,
        new_critical_errors=sorted(cand_critical - base_critical),
        resolved_critical_errors=sorted(base_critical - cand_critical),
    )
    if base_mean is None or cand_mean is None:
        change.reasons.append("Comparaison impossible : aucun run évalué dans l'un des deux bras")
        return change
    delta = cand_mean - base_mean
    change.delta = delta
    new_gate = cand_gate > 0 and base_gate == 0
    fixed_gate = base_gate > 0 and cand_gate == 0
    if delta <= -threshold or new_gate or change.new_critical_errors:
        change.status = "regression"
        change.severity = _magnitude(-delta, hard_failure=new_gate or bool(change.new_critical_errors))
        if delta <= -threshold:
            change.reasons.append(
                f"Score composite {fr_number(delta, 1, signed=True)} points "
                f"(seuil de bruit −{fr_number(threshold, 1)})"
            )
        if new_gate:
            change.reasons.append(f"Nouveau garde-fou en échec ({cand_gate} run(s) de la candidate)")
        if change.new_critical_errors:
            change.reasons.append(
                "Nouvelle(s) erreur(s) critique(s) : " + ", ".join(change.new_critical_errors)
            )
    elif delta >= threshold or fixed_gate or change.resolved_critical_errors:
        change.status = "improvement"
        change.severity = _magnitude(delta, hard_failure=fixed_gate or bool(change.resolved_critical_errors))
        if delta >= threshold:
            change.reasons.append(
                f"Score composite {fr_number(delta, 1, signed=True)} points "
                f"(seuil de bruit +{fr_number(threshold, 1)})"
            )
        if fixed_gate:
            change.reasons.append("Garde-fou de nouveau respecté par la candidate")
        if change.resolved_critical_errors:
            change.reasons.append(
                "Erreur(s) critique(s) corrigée(s) : " + ", ".join(change.resolved_critical_errors)
            )
    else:
        change.status = "stable"
    return change


_SEVERITY_ORDER = {RegressionSeverity.minor: 0, RegressionSeverity.major: 1, RegressionSeverity.critical: 2}


def _severity_rank(severity: RegressionSeverity) -> int:
    return _SEVERITY_ORDER[severity]


def _change_sort_key(change: ScenarioChange) -> tuple[int, float, str]:
    rank = _severity_rank(change.severity) if change.severity else -1
    return (-rank, change.delta if change.status == "regression" else -(change.delta or 0.0), change.name)


# =====================================================================================================
# Errors
# =====================================================================================================


def _max_severity(values: Sequence[str]) -> str:
    best = ErrorSeverity.low
    for value in values:
        try:
            severity = ErrorSeverity(value)
        except ValueError:
            continue
        if SEVERITY_RANK[severity] > SEVERITY_RANK[best]:
            best = severity
    return best.value


def compare_errors(baseline: Sequence[RunSummary], candidate: Sequence[RunSummary]) -> ErrorsComparison:
    base_exec = [r for r in baseline if r.status != RunStatus.cancelled]
    cand_exec = [r for r in candidate if r.status != RunStatus.cancelled]
    base_counts = Counter(t for r in base_exec for t, _ in r.errors)
    cand_counts = Counter(t for r in cand_exec for t, _ in r.errors)
    severities: dict[str, list[str]] = defaultdict(list)
    for run in [*base_exec, *cand_exec]:
        for error_type, severity in run.errors:
            severities[error_type].append(severity)
    changes: list[ErrorChange] = []
    for error_type in sorted(set(base_counts) | set(cand_counts)):
        b, c = base_counts.get(error_type, 0), cand_counts.get(error_type, 0)
        b_rate, c_rate = rate(b, len(base_exec)), rate(c, len(cand_exec))
        delta_rate = c_rate - b_rate if b_rate is not None and c_rate is not None else None
        if b == 0 and c > 0:
            kind = "appeared"
        elif c == 0 and b > 0:
            kind = "disappeared"
        elif delta_rate is not None and delta_rate >= ERROR_RATE_CHANGE:
            kind = "increased"
        elif delta_rate is not None and delta_rate <= -ERROR_RATE_CHANGE:
            kind = "decreased"
        else:
            kind = "stable"
        changes.append(
            ErrorChange(
                error_type=error_type,
                baseline_count=b,
                candidate_count=c,
                baseline_rate=b_rate,
                candidate_rate=c_rate,
                delta_rate=delta_rate,
                max_severity=_max_severity(severities[error_type]),
                change=kind,
            )
        )
    changes.sort(key=lambda ch: (-(abs(ch.delta_rate or 0.0)), ch.error_type))
    return ErrorsComparison(
        appeared=sorted(ch.error_type for ch in changes if ch.change == "appeared"),
        disappeared=sorted(ch.error_type for ch in changes if ch.change == "disappeared"),
        changes=changes,
        baseline_error_rate=rate(sum(1 for r in base_exec if r.errors), len(base_exec)),
        candidate_error_rate=rate(sum(1 for r in cand_exec if r.errors), len(cand_exec)),
    )


# =====================================================================================================
# Comparison
# =====================================================================================================


def arm_summary(
    arm: ExperimentArm, runs: Sequence[RunSummary], *, robustness_max_std: float = DEFAULT_ROBUSTNESS_MAX_STD
) -> ArmSummary:
    scored = [r for r in runs if is_scored(r)]
    executed = [r for r in runs if r.status != RunStatus.cancelled]
    labels = Counter(r.agent_label for r in runs)
    versions = Counter(r.agent_version_id for r in runs)
    return ArmSummary(
        arm=arm,
        agent_version_id=versions.most_common(1)[0][0] if versions else None,
        agent_label=labels.most_common(1)[0][0]
        if labels
        else ("Baseline" if arm == ExperimentArm.baseline else "Candidate"),
        n_runs=len(runs),
        n_scored=len(scored),
        n_failed=sum(1 for r in runs if r.status == RunStatus.failed),
        n_cancelled=sum(1 for r in runs if r.status == RunStatus.cancelled),
        composite_mean=mean(r.composite for r in scored),
        pass_rate=rate(sum(1 for r in scored if r.passed), len(scored)),
        gate_failure_rate=rate(sum(1 for r in scored if r.gate_failed), len(scored)),
        error_rate=rate(sum(1 for r in executed if r.errors), len(executed)),
        robustness=robustness(scored, max_std=robustness_max_std).value,
    )


def compare(
    baseline: Sequence[RunSummary],
    candidate: Sequence[RunSummary],
    *,
    robustness_max_std: float = DEFAULT_ROBUSTNESS_MAX_STD,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
    warnings: Sequence[str] = (),
) -> ExperimentComparison:
    """Compare the baseline and candidate runs of an experiment (docs §9.3)."""
    from forge.domain.experiments.recommendation import recommend

    stats_kwargs = {"confidence": confidence, "n_resamples": n_resamples, "seed": seed}
    base_arm = arm_summary(ExperimentArm.baseline, baseline, robustness_max_std=robustness_max_std)
    cand_arm = arm_summary(ExperimentArm.candidate, candidate, robustness_max_std=robustness_max_std)

    composite = compare_metric(
        "composite",
        "Score composite",
        _per_scenario(baseline, _composite_points),
        _per_scenario(candidate, _composite_points),
        **stats_kwargs,
    )
    dim_keys = sorted(
        {k for r in baseline if is_scored(r) for k in r.dimensions}
        & {k for r in candidate if is_scored(r) for k in r.dimensions},
        key=dimension_sort_key,
    )
    dimensions = [
        compare_metric(
            key,
            dimension_label(key),
            _per_scenario(baseline, _dimension_points(key)),
            _per_scenario(candidate, _dimension_points(key)),
            **stats_kwargs,
        )
        for key in dim_keys
        if key not in {d.value for d in GROUP_DIMENSIONS}
    ]
    resources = [
        _resource("cost", "€", baseline, candidate, lambda r: r.cost),
        _resource("latency", "ms", baseline, candidate, lambda r: r.latency_ms),
        _resource(
            "tokens",
            "tokens",
            baseline,
            candidate,
            lambda r: float(r.tokens) if r.tokens is not None else None,
        ),
    ]

    by_scenario_base: dict[str, list[RunSummary]] = defaultdict(list)
    by_scenario_cand: dict[str, list[RunSummary]] = defaultdict(list)
    order: list[str] = []
    for run in baseline:
        if (
            run.scenario_version_id not in by_scenario_base
            and run.scenario_version_id not in by_scenario_cand
        ):
            order.append(run.scenario_version_id)
        by_scenario_base[run.scenario_version_id].append(run)
    for run in candidate:
        if (
            run.scenario_version_id not in by_scenario_base
            and run.scenario_version_id not in by_scenario_cand
        ):
            order.append(run.scenario_version_id)
        by_scenario_cand[run.scenario_version_id].append(run)
    scenarios = [
        scenario_change(by_scenario_base.get(key, []), by_scenario_cand.get(key, [])) for key in order
    ]
    regressions = sorted((s for s in scenarios if s.status == "regression"), key=_change_sort_key)
    improvements = sorted((s for s in scenarios if s.status == "improvement"), key=_change_sort_key)

    cells = [
        [float(r.composite) for r in runs if is_scored(r) and r.composite is not None]
        for group in (by_scenario_base, by_scenario_cand)
        for runs in group.values()
    ]
    pooled, dof = pooled_std(cells)
    repetitions = max((r.repetition for r in [*baseline, *candidate]), default=-1) + 1

    base_rob, cand_rob = base_arm.robustness, cand_arm.robustness
    robust = RobustnessComparison(
        baseline=base_rob,
        candidate=cand_rob,
        delta=(cand_rob - base_rob) * 100.0 if base_rob is not None and cand_rob is not None else None,
    )
    errors = compare_errors(baseline, candidate)
    all_warnings = list(warnings)
    n_unpaired = sum(1 for s in scenarios if s.status == "unpaired")
    if n_unpaired:
        all_warnings.append(
            f"{n_unpaired} scénario(s) sans run évalué dans les deux bras : exclu(s) de la comparaison."
        )
    if repetitions <= 1:
        all_warnings.append(
            "Une seule répétition : le bruit par scénario n'est pas mesurable (σ par défaut de 5 points)."
        )
    recommendation = recommend(
        composite=composite,
        dimensions=dimensions,
        resources=resources,
        regressions=regressions,
        improvements=improvements,
        errors=errors,
        baseline_label=base_arm.agent_label,
        candidate_label=cand_arm.agent_label,
        n_unpaired=n_unpaired,
        confidence=confidence,
    )
    return ExperimentComparison(
        schema=COMPARISON_SCHEMA,
        baseline=base_arm,
        candidate=cand_arm,
        n_pairs=composite.n_pairs,
        n_unpaired=n_unpaired,
        composite=composite,
        dimensions=dimensions,
        resources=resources,
        scenarios=scenarios,
        regressions=regressions,
        improvements=improvements,
        errors=errors,
        robustness=robust,
        noise=NoiseInfo(pooled_std=pooled, dof=dof, repetitions=max(1, repetitions)),
        recommendation=recommendation,
        warnings=all_warnings,
        statistics=ComparisonStatistics(confidence=confidence, n_resamples=n_resamples, seed=seed),
    )
