"""Production monitoring: window health and in-flight failure risk (pure rules)."""

from __future__ import annotations

from forge.domain.enums import ScenarioVisibility
from forge.domain.monitoring import (
    Budget,
    Progress,
    Reference,
    ToolStep,
    WindowStats,
    assess_risk,
    health_verdict,
    percentile,
    summarize,
    worse_proportion_p,
)
from forge.domain.types import RunSummary


def run(
    *, status="completed", composite=80.0, passed=True, cost=0.1, latency=1000.0, errors=()
) -> RunSummary:
    return RunSummary(
        run_id="r", scenario_id="s", scenario_version_id="sv", scenario_slug="s", scenario_name="S", family_id="f",
        category="c", difficulty="medium", visibility=ScenarioVisibility.public, agent_id="a", agent_version_id="av",
        agent_label="A v1", model=None, repetition=0, status=status, composite=composite, passed=passed,
        gate_failed=False, cost=cost, latency_ms=latency, errors=list(errors),
    )  # fmt: skip


def window(n, passed, failed=0, **kw) -> WindowStats:
    runs = [run() for _ in range(passed)] + [
        run(passed=False, composite=40.0) for _ in range(n - passed - failed)
    ]
    runs += [run(status="failed", composite=None, passed=None) for _ in range(failed)]
    return summarize(runs)


def test_summarize_computes_rates_cost_per_success_and_p95():
    stats = summarize(
        [run(cost=0.1, latency=100), run(cost=0.3, latency=300), run(passed=False, composite=30.0, cost=0.2, latency=900, errors=[("X", "high")]),
         run(status="failed", composite=None, passed=None, cost=None, latency=None)]
    )  # fmt: skip
    assert stats.n_runs == 4 and stats.n_scored == 3 and stats.n_failed == 1 and stats.n_passed == 2
    assert stats.pass_rate == 2 / 3 and stats.failure_rate == 0.25 and stats.error_rate == 1 / 3
    assert stats.cost_per_success == 0.3  # 0.6 spent for 2 successes
    assert stats.latency_p95 == 900
    assert summarize([]).pass_rate is None and percentile([], 0.95) is None


def test_the_proportion_test_only_flags_real_increases():
    assert worse_proportion_p(30, 100, 10, 100) < 0.01  # 30 % vs 10 % bad
    assert worse_proportion_p(11, 100, 10, 100) > 0.4  # noise
    assert worse_proportion_p(5, 100, 20, 100) > 0.9  # improvement is never "worse"
    assert worse_proportion_p(0, 0, 1, 10) is None


def test_too_few_runs_never_raise_an_alarm():
    health = health_verdict(window(5, 0), window(100, 90))
    assert health.status == "insufficient_data" and not health.alerts and "5 récents" in health.reason


def test_a_significant_drop_in_pass_rate_degrades_the_agent():
    health = health_verdict(window(60, 30), window(200, 170))
    assert health.status == "degraded"
    assert health.alerts[0].kind == "pass_rate_drop" and health.alerts[0].p_value < 0.05
    assert "50%" in health.alerts[0].message and "85%" in health.alerts[0].message


def test_noise_and_small_changes_stay_healthy():
    assert health_verdict(window(60, 50), window(200, 170)).status == "healthy"  # 83 % vs 85 %
    assert health_verdict(window(60, 56), window(200, 170)).status == "healthy"  # improvement


def test_execution_failures_cost_and_latency_each_raise_their_own_alert():
    previous = summarize([run(cost=0.1, latency=1000) for _ in range(40)])
    recent = summarize(
        [run(cost=0.2, latency=2500) for _ in range(20)] + [run(status="failed", composite=None, passed=None) for _ in range(10)]
    )  # fmt: skip
    kinds = {a.kind for a in health_verdict(recent, previous).alerts}
    assert {"failure_rate_rise", "cost_per_success_rise", "latency_p95_rise"} <= kinds


REFERENCE = Reference(n_runs=50, latency_p95_ms=10_000, tokens_p95=20_000)


def test_a_finished_or_quiet_run_is_low_risk():
    assert assess_risk(Progress(elapsed_ms=2000, tokens=3000), REFERENCE, Budget()).level == "low"
    done = assess_risk(Progress(elapsed_ms=2000, has_final_answer=True, error_events=5), REFERENCE, Budget())
    assert done.finished and done.level == "low" and done.score == 0.0


def test_a_repeated_tool_call_is_a_loop():
    loop = [ToolStep("search", {"q": "refund"}) for _ in range(3)]
    risk = assess_risk(Progress(elapsed_ms=1000, tool_steps=loop), REFERENCE, Budget())
    assert risk.level == "medium" and [s.kind for s in risk.signals] == ["tool_loop"]
    varied = [ToolStep("search", {"q": str(i)}) for i in range(5)]
    assert assess_risk(Progress(elapsed_ms=1000, tool_steps=varied), REFERENCE, Budget()).level == "low"


def test_independent_signals_combine_into_a_high_risk():
    steps = [ToolStep("db", {"id": 1}, failed=True) for _ in range(3)]
    risk = assess_risk(
        Progress(elapsed_ms=30_000, tokens=50_000, tool_steps=steps, error_events=2),
        REFERENCE,
        Budget(max_tokens=55_000),
    )
    kinds = {s.kind for s in risk.signals}
    assert {"tool_loop", "tool_errors", "error_events", "slow", "token_overrun", "token_budget"} <= kinds
    assert risk.level == "high" and 0.9 < risk.score <= 1.0


def test_reference_signals_need_enough_successful_runs_but_budgets_do_not():
    thin = Reference(n_runs=3, latency_p95_ms=1000, tokens_p95=1000)
    assert assess_risk(Progress(elapsed_ms=60_000, tokens=100_000), thin, Budget()).signals == []
    risk = assess_risk(
        Progress(elapsed_ms=90_000, tokens=100, cost=0.9), thin, Budget(max_cost=1.0, timeout_seconds=100)
    )
    assert {s.kind for s in risk.signals} == {"cost_budget", "timeout"}
