"""Production monitoring (ORION): is an agent getting worse, and is a run in flight about to fail?

Pure functions, no I/O.

* **Release health** — per-release statistics of the runs a release produced (``summarize``).
* **Agent health** — a recent window against the one before it: a one-sided two-proportion z-test on the pass
  rate and on the failure rate (an alert needs both significance *and* a meaningful drop), plus rises of
  the cost per success and of the p95 latency. Too few runs → ``insufficient_data``, never a false alarm.
* **Run risk** — signs of failure *before* the run ends: a tool call repeated with the same arguments (loop),
  repeated tool errors, time or tokens far above what successful runs of the same agent version needed, and
  budget burned. The score combines independent signals as ``1 - Π(1 - weight)``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from forge.domain.types import RunSummary

ALPHA = 0.05
MIN_PASS_RATE_DROP = 0.05
MIN_FAILURE_RATE_RISE = 0.05
MAX_COST_INCREASE = 0.25
MAX_LATENCY_INCREASE = 0.5
MIN_RUNS = 10


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def percentile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


# =====================================================================================================
# Release / window statistics
# =====================================================================================================


@dataclass(slots=True)
class WindowStats:
    n_runs: int = 0
    n_scored: int = 0
    n_failed: int = 0
    n_passed: int = 0
    composite_mean: float | None = None
    pass_rate: float | None = None
    failure_rate: float | None = None
    error_rate: float | None = None
    cost_mean: float | None = None
    cost_per_success: float | None = None
    latency_p95: float | None = None


def summarize(runs: Sequence[RunSummary]) -> WindowStats:
    scored = [r for r in runs if r.composite is not None]
    failed = [r for r in runs if r.status == "failed"]
    passed = [r for r in scored if r.passed]
    costs = [r.cost for r in runs if r.cost is not None]
    latencies = [r.latency_ms for r in runs if r.latency_ms is not None]
    total_cost = sum(costs)
    return WindowStats(
        n_runs=len(runs),
        n_scored=len(scored),
        n_failed=len(failed),
        n_passed=len(passed),
        composite_mean=_mean([r.composite for r in scored if r.composite is not None]),
        pass_rate=len(passed) / len(scored) if scored else None,
        failure_rate=len(failed) / len(runs) if runs else None,
        error_rate=sum(1 for r in scored if r.errors) / len(scored) if scored else None,
        cost_mean=_mean(costs),
        cost_per_success=total_cost / len(passed) if passed and costs else None,
        latency_p95=percentile(latencies, 0.95),
    )


# =====================================================================================================
# Agent health: recent window vs previous window
# =====================================================================================================


def worse_proportion_p(bad_recent: int, n_recent: int, bad_previous: int, n_previous: int) -> float | None:
    """One-sided p-value that the recent share of ``bad`` outcomes is higher than the previous one."""
    if n_recent <= 0 or n_previous <= 0:
        return None
    pooled = (bad_recent + bad_previous) / (n_recent + n_previous)
    spread = math.sqrt(pooled * (1 - pooled) * (1 / n_recent + 1 / n_previous))
    if spread == 0:
        return 1.0 if bad_recent / n_recent <= bad_previous / n_previous else 0.0
    z = (bad_recent / n_recent - bad_previous / n_previous) / spread
    return 0.5 * math.erfc(z / math.sqrt(2))


@dataclass(slots=True)
class Alert:
    kind: str  # pass_rate_drop | failure_rate_rise | cost_per_success_rise | latency_p95_rise
    message: str
    recent: float | None = None
    previous: float | None = None
    p_value: float | None = None


@dataclass(slots=True)
class Health:
    status: str  # healthy | degraded | insufficient_data
    recent: WindowStats
    previous: WindowStats
    alerts: list[Alert] = field(default_factory=list)
    reason: str = ""


def _relative_rise(recent: float | None, previous: float | None) -> float | None:
    if recent is None or previous is None or previous <= 0:
        return None
    return (recent - previous) / previous


def health_verdict(recent: WindowStats, previous: WindowStats, *, min_runs: int = MIN_RUNS) -> Health:
    if recent.n_runs < min_runs or previous.n_runs < min_runs:
        return Health(
            "insufficient_data",
            recent,
            previous,
            reason=(
                f"Pas assez de runs pour juger ({recent.n_runs} récents, {previous.n_runs} avant ; "
                f"{min_runs} requis)."
            ),
        )
    alerts: list[Alert] = []
    if (
        recent.n_scored
        and previous.n_scored
        and recent.pass_rate is not None
        and previous.pass_rate is not None
    ):
        p = worse_proportion_p(
            recent.n_scored - recent.n_passed,
            recent.n_scored,
            previous.n_scored - previous.n_passed,
            previous.n_scored,
        )
        drop = previous.pass_rate - recent.pass_rate
        if p is not None and p < ALPHA and drop >= MIN_PASS_RATE_DROP:
            alerts.append(
                Alert(
                    "pass_rate_drop",
                    f"Taux de réussite {recent.pass_rate:.0%} contre {previous.pass_rate:.0%} auparavant.",
                    recent.pass_rate,
                    previous.pass_rate,
                    round(p, 4),
                )
            )
    if recent.failure_rate is not None and previous.failure_rate is not None:
        p = worse_proportion_p(recent.n_failed, recent.n_runs, previous.n_failed, previous.n_runs)
        rise = recent.failure_rate - previous.failure_rate
        if p is not None and p < ALPHA and rise >= MIN_FAILURE_RATE_RISE:
            alerts.append(
                Alert(
                    "failure_rate_rise",
                    f"Échecs {recent.failure_rate:.0%} contre {previous.failure_rate:.0%} auparavant.",
                    recent.failure_rate,
                    previous.failure_rate,
                    round(p, 4),
                )
            )
    cost_rise = _relative_rise(recent.cost_per_success, previous.cost_per_success)
    if cost_rise is not None and cost_rise > MAX_COST_INCREASE:
        alerts.append(
            Alert(
                "cost_per_success_rise",
                f"Le coût par réussite a augmenté de {cost_rise:.0%}.",
                recent.cost_per_success,
                previous.cost_per_success,
            )
        )
    latency_rise = _relative_rise(recent.latency_p95, previous.latency_p95)
    if latency_rise is not None and latency_rise > MAX_LATENCY_INCREASE:
        alerts.append(
            Alert(
                "latency_p95_rise",
                f"La latence p95 a augmenté de {latency_rise:.0%}.",
                recent.latency_p95,
                previous.latency_p95,
            )
        )
    if alerts:
        return Health("degraded", recent, previous, alerts, reason=f"{len(alerts)} signal(s) de dégradation.")
    return Health("healthy", recent, previous, reason="Aucune dégradation significative.")


# =====================================================================================================
# In-flight run risk
# =====================================================================================================

LOOP_REPEATS = 3
TOOL_ERROR_LIMIT = 3
OVERRUN_FACTOR = 2.0
BUDGET_ALERT_SHARE = 0.8
MIN_REFERENCE_RUNS = 10


@dataclass(slots=True)
class ToolStep:
    name: str
    arguments: Any
    failed: bool = False

    @property
    def signature(self) -> str:
        blob = json.dumps(self.arguments, sort_keys=True, default=str)
        return f"{self.name}:{hashlib.sha1(blob.encode()).hexdigest()[:12]}"


@dataclass(slots=True)
class Progress:
    elapsed_ms: float
    tokens: int = 0
    cost: float = 0.0
    tool_steps: list[ToolStep] = field(default_factory=list)
    error_events: int = 0
    has_final_answer: bool = False


@dataclass(slots=True)
class Reference:
    """What successful runs of the same agent version needed."""

    n_runs: int = 0
    latency_p95_ms: float | None = None
    tokens_p95: float | None = None


@dataclass(slots=True)
class Budget:
    max_tokens: int | None = None
    max_cost: float | None = None
    timeout_seconds: float | None = None


@dataclass(slots=True)
class Signal:
    kind: str
    message: str
    weight: float


@dataclass(slots=True)
class Risk:
    level: str  # low | medium | high
    score: float
    signals: list[Signal] = field(default_factory=list)
    finished: bool = False


def assess_risk(progress: Progress, reference: Reference, budget: Budget) -> Risk:
    if progress.has_final_answer:
        return Risk("low", 0.0, [], finished=True)
    signals: list[Signal] = []
    seen: dict[str, int] = {}
    for step in progress.tool_steps:
        seen[step.signature] = seen.get(step.signature, 0) + 1
    repeated = max(seen.values(), default=0)
    if repeated >= LOOP_REPEATS:
        signals.append(
            Signal("tool_loop", f"Le même appel d'outil a été répété {repeated} fois sans progrès.", 0.5)
        )
    tool_errors = sum(1 for s in progress.tool_steps if s.failed)
    if tool_errors >= TOOL_ERROR_LIMIT:
        signals.append(Signal("tool_errors", f"{tool_errors} appels d'outils ont échoué.", 0.4))
    if progress.error_events:
        signals.append(
            Signal("error_events", f"{progress.error_events} erreur(s) signalée(s) pendant l'exécution.", 0.2)
        )
    enough = reference.n_runs >= MIN_REFERENCE_RUNS
    if (
        enough
        and reference.latency_p95_ms
        and progress.elapsed_ms > OVERRUN_FACTOR * reference.latency_p95_ms
    ):
        signals.append(
            Signal(
                "slow",
                f"Déjà {progress.elapsed_ms / 1000:.0f} s : plus du double de 95 % des runs réussis.",
                0.3,
            )
        )
    if enough and reference.tokens_p95 and progress.tokens > OVERRUN_FACTOR * reference.tokens_p95:
        signals.append(
            Signal(
                "token_overrun", f"{progress.tokens} tokens consommés, bien au-delà des runs réussis.", 0.3
            )
        )
    if budget.max_tokens and progress.tokens >= BUDGET_ALERT_SHARE * budget.max_tokens:
        signals.append(Signal("token_budget", "Plus de 80 % du budget de tokens est consommé.", 0.4))
    if budget.max_cost and progress.cost >= BUDGET_ALERT_SHARE * budget.max_cost:
        signals.append(Signal("cost_budget", "Plus de 80 % du budget de coût est consommé.", 0.4))
    if budget.timeout_seconds and progress.elapsed_ms >= BUDGET_ALERT_SHARE * budget.timeout_seconds * 1000:
        signals.append(Signal("timeout", "Le run approche de sa durée maximale.", 0.3))
    miss = 1.0
    for signal in signals:
        miss *= 1 - signal.weight
    score = round(1 - miss, 3)
    level = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"
    return Risk(level, score, signals)
