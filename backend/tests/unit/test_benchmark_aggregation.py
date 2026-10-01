"""Benchmark aggregation (§9.1), robustness (§9.2), generalisation gap, groupings, ranking."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import numpy as np
import pytest

from forge.domain.benchmarks import (
    GROUP_BY_VALUES,
    aggregate_benchmark,
    error_breakdown,
    group_composite,
    group_runs,
    robustness,
)
from forge.domain.defaults import DEFAULT_DIMENSION_WEIGHTS
from forge.domain.enums import ScenarioVisibility
from forge.domain.types import to_dict
from tests.unit.analytics_builders import make_run, sid

WEIGHTS = {str(k): v for k, v in DEFAULT_DIMENSION_WEIGHTS.items()}


def _two_agents() -> list:
    runs = []
    for rep in range(2):
        for scenario, base in (("s1", 70.0), ("s2", 80.0), ("s3", 90.0)):
            runs.append(make_run(scenario=scenario, agent="A", composite=base + rep, repetition=rep))
            runs.append(
                make_run(
                    scenario=scenario,
                    agent="B",
                    composite=base - 20 + rep,
                    repetition=rep,
                    errors=[("HALLUCINATION", "high")] if scenario == "s1" else [],
                )
            )
    return runs


def test_aggregate_per_agent_and_ranking() -> None:
    summary = aggregate_benchmark(_two_agents(), dimension_weights=WEIGHTS, n_resamples=2000)
    assert summary.schema == "forge.benchmark-summary/v1"
    assert summary.totals.n_runs == 12 and summary.totals.n_scored == 12
    assert summary.totals.n_scenarios == 3 and summary.totals.n_agents == 2 and summary.totals.repetitions == 2
    first, second = summary.agents
    assert (first.agent_label, first.rank) == ("A v1.0", 1)
    assert first.composite.mean == pytest.approx(80.5)
    assert first.composite.ci_low < 80.5 < first.composite.ci_high
    assert first.pass_rate == 1.0
    assert second.pass_rate == pytest.approx(2 / 6)  # 70 and 71 on s3
    assert second.errors_by_type == {"HALLUCINATION": 2}
    assert second.error_rate == pytest.approx(2 / 6)
    assert [r.agent_label for r in summary.ranking] == ["A v1.0", "B v1.0"]
    # Group composites: both equally robust, so the gap is (1 − robustness share) × 20 points.
    assert summary.ranking[1].delta_to_leader == pytest.approx(-18.0, abs=0.1)
    assert second.vs_leader is not None and second.vs_leader.delta == pytest.approx(-20.0)
    # Only 3 paired scenarios: the gap is large but cannot be significant with Wilcoxon.
    assert summary.ranking[1].significant_gap is False
    assert second.vs_leader is not None and second.vs_leader.n_pairs == 3
    best = {b.dimension: b.agent_label for b in summary.best_by_dimension}
    assert best["quality"] == "A v1.0"


def test_failed_runs_count_as_zero_and_cancelled_are_ignored() -> None:
    runs = [
        make_run(scenario="s1", composite=90.0),
        make_run(scenario="s2", composite=0.0, status="failed", passed=False, errors=[("TIMEOUT", "high")]),
        make_run(scenario="s3", composite=None, status="cancelled", cost=None, latency_ms=None),
        make_run(scenario="s4", composite=None, status="running", cost=None, latency_ms=None),
    ]
    summary = aggregate_benchmark(runs, dimension_weights=WEIGHTS, n_resamples=500)
    agent = summary.agents[0]
    assert (agent.n_runs, agent.n_scored, agent.n_failed, agent.n_cancelled) == (4, 2, 1, 1)
    assert agent.composite.mean == 45.0
    assert agent.pass_rate == 0.5
    assert summary.totals.n_pending == 1
    assert agent.cost.n == 2  # the running run has no cost yet, the cancelled one is excluded


def test_gate_failures_cost_latency_tokens() -> None:
    runs = [
        make_run(scenario="s1", composite=0.0, gate_failed=True, cost=0.02, latency_ms=1000, tokens=100),
        make_run(scenario="s2", composite=80.0, cost=0.04, latency_ms=3000, tokens=300),
        make_run(scenario="s3", composite=85.0, cost=0.06, latency_ms=5000, tokens=500),
    ]
    agent = aggregate_benchmark(runs, dimension_weights=WEIGHTS, n_resamples=500).agents[0]
    assert agent.gate_failure_rate == pytest.approx(1 / 3)
    assert agent.cost.mean == pytest.approx(0.04) and agent.cost.total == pytest.approx(0.12)
    assert agent.latency.mean == 3000 and agent.latency.p95 == pytest.approx(4800)
    assert agent.tokens.total == 900


def test_robustness_formula_and_group_composite() -> None:
    # Family F: root s1 + variant s1b, 2 repetitions each → 4 composites.
    composites = [80.0, 60.0, 70.0, 90.0]
    runs = [
        make_run(scenario="s1", composite=composites[0], repetition=0),
        make_run(scenario="s1", composite=composites[1], repetition=1),
        make_run(scenario="s1b", family="s1", composite=composites[2], repetition=0),
        make_run(scenario="s1b", family="s1", composite=composites[3], repetition=1),
        make_run(scenario="s2", composite=75.0),  # single run: no dispersion
    ]
    result = robustness(runs, max_std=0.25)
    sigma = float(np.std(np.array(composites) / 100, ddof=1))
    assert result.n_families == 1
    family = result.families[0]
    assert family.label == "Scénario s1" and family.n_runs == 4 and family.n_scenarios == 2
    assert family.std == pytest.approx(sigma)
    assert result.value == pytest.approx(1 - min(1, sigma / 0.25))
    agent = aggregate_benchmark(runs, dimension_weights=WEIGHTS, n_resamples=500).agents[0]
    assert agent.dimensions["robustness"] == pytest.approx(result.value)
    share = WEIGHTS["robustness"] / sum(WEIGHTS.values())
    expected = (1 - share) * agent.composite.mean + share * 100 * result.value
    assert agent.group_composite == pytest.approx(expected)


def test_robustness_weighted_by_family_size_and_capped() -> None:
    runs = [make_run(scenario="a", composite=v, repetition=i) for i, v in enumerate([50.0, 50.0])]
    runs += [make_run(scenario="b", composite=v, repetition=i) for i, v in enumerate([0.0, 100.0, 0.0, 100.0])]
    result = robustness(runs, max_std=0.25)
    by_label = {f.label: f.robustness for f in result.families}
    assert by_label == {"Scénario a": 1.0, "Scénario b": 0.0}
    assert result.value == pytest.approx((1.0 * 2 + 0.0 * 4) / 6)
    assert robustness([make_run()], max_std=0.25).value is None


def test_group_composite_without_robustness_weight() -> None:
    assert group_composite(70.0, None, WEIGHTS) == 70.0
    assert group_composite(70.0, 0.5, {"quality": 1.0}) == 70.0
    assert group_composite(None, 0.5, WEIGHTS) is None
    assert group_composite(70.0, 1.0, {"quality": 0.5, "robustness": 0.5}) == pytest.approx(85.0)


def test_generalisation_gap() -> None:
    runs = [
        make_run(scenario="p1", composite=90.0),
        make_run(scenario="p2", composite=86.0),
        make_run(scenario="h1", composite=70.0, visibility=ScenarioVisibility.private),
        make_run(scenario="h2", composite=74.0, visibility=ScenarioVisibility.fresh),
    ]
    gen = aggregate_benchmark(runs, dimension_weights=WEIGHTS, n_resamples=500).agents[0].generalisation
    assert gen.public_mean == 88.0 and gen.hidden_mean == 72.0
    assert gen.private_mean == 70.0 and gen.fresh_mean == 74.0
    assert gen.gap == 16.0 and gen.alert is True
    assert (gen.n_public, gen.n_hidden) == (2, 2)


def test_matrix_cells() -> None:
    summary = aggregate_benchmark(_two_agents(), dimension_weights=WEIGHTS, n_resamples=500)
    matrix = summary.matrix
    assert [s.slug for s in matrix.scenarios] == ["s1", "s2", "s3"]
    assert [a.label for a in matrix.agents] == ["A v1.0", "B v1.0"]
    assert len(matrix.cells) == 6
    cell = next(c for c in matrix.cells if c.scenario_id == sid("scenario:s1") and c.agent_version_id.endswith(""))
    assert cell.n_runs == 2 and cell.composite_mean == pytest.approx(70.5)
    b_s1 = next(
        c for c in matrix.cells if c.scenario_id == sid("scenario:s1") and c.agent_version_id == sid("agent-version:B:1.0")
    )
    assert b_s1.error_types == ["HALLUCINATION"] and b_s1.error_count == 2


def test_group_runs_every_dimension() -> None:
    runs = _two_agents() + [
        make_run(
            scenario="s4",
            agent="A",
            version="2.0",
            composite=60.0,
            category="compliance",
            difficulty="hard",
            model=None,
            created_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
    ]
    for group_by in GROUP_BY_VALUES:
        rows = group_runs(runs, group_by)
        assert rows, group_by
        assert sum(r.n_runs for r in rows) >= len(runs)
    by_version = group_runs(runs, "version", with_ci=True, n_resamples=500)
    assert [r.label for r in by_version] == ["A v1.0", "B v1.0", "A v2.0"]
    assert by_version[0].composite_ci_low is not None
    by_agent = group_runs(runs, "agent")
    assert {r.label for r in by_agent} == {"A", "B"}
    assert next(r for r in by_agent if r.label == "A").n_runs == 7
    by_category = {r.key: r.label for r in group_runs(runs, "category")}
    assert by_category == {"compliance": "Conformité", "product_management": "Product Management"}
    by_model = {r.label for r in group_runs(runs, "model")}
    assert "Modèle non renseigné" in by_model
    by_date = [r.key for r in group_runs(runs, "date")]
    assert by_date == ["2026-09-01", "2026-09-02"]
    by_difficulty = [r.key for r in group_runs(runs, "difficulty")]
    assert by_difficulty == ["medium", "hard"]
    by_error = group_runs(runs, "error_type")
    assert by_error[0].key == "HALLUCINATION" and by_error[0].n_runs == 2
    assert by_error[-1].key == "none" and by_error[-1].label == "Aucune erreur"
    with pytest.raises(ValueError):
        group_runs(runs, "unknown")


def test_error_breakdown() -> None:
    runs = [
        make_run(errors=[("FORMAT_ERROR", "low"), ("FORMAT_ERROR", "medium")]),
        make_run(agent="B", errors=[("FORMAT_ERROR", "critical"), ("HALLUCINATION", "high")]),
        make_run(status="cancelled", composite=None, errors=[("HALLUCINATION", "high")]),
    ]
    rows = error_breakdown(runs)
    assert [(r.error_type, r.count, r.runs_affected, r.max_severity) for r in rows] == [
        ("FORMAT_ERROR", 3, 2, "critical"),
        ("HALLUCINATION", 1, 1, "high"),
    ]
    assert rows[0].by_severity == {"critical": 1, "low": 1, "medium": 1}


def test_summary_is_deterministic_and_json_ready() -> None:
    import json

    first = to_dict(aggregate_benchmark(_two_agents(), dimension_weights=WEIGHTS, n_resamples=1000))
    second = to_dict(aggregate_benchmark(_two_agents(), dimension_weights=WEIGHTS, n_resamples=1000))
    for payload in (first, second):
        for agent in payload["agents"]:
            agent.pop("agent_version_id")
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_empty_benchmark() -> None:
    summary = aggregate_benchmark([], dimension_weights=WEIGHTS)
    assert summary.agents == [] and summary.ranking == [] and summary.totals.n_runs == 0


def test_aggregation_performance_1200_runs() -> None:
    rng = np.random.default_rng(42)
    runs = []
    for agent_index in range(4):
        for scenario in range(100):
            for rep in range(3):
                composite = float(np.clip(rng.normal(60 + 5 * agent_index, 10), 0, 100))
                runs.append(
                    make_run(
                        scenario=f"s{scenario}",
                        family=f"s{scenario - scenario % 4}",
                        agent=f"Agent{agent_index}",
                        composite=composite,
                        repetition=rep,
                        dimensions={"quality": composite / 100, "safety": 0.9, "cost": 0.8},
                        errors=[("FORMAT_ERROR", "low")] if rng.random() < 0.2 else [],
                        category=["delivery", "discovery", "compliance"][scenario % 3],
                    )
                )
    started = time.perf_counter()
    summary = aggregate_benchmark(runs, dimension_weights=WEIGHTS)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, elapsed
    assert summary.totals.n_runs == 1200
    assert summary.ranking[0].agent_label == "Agent3 v1.0"
    assert summary.ranking[1].significant_gap is True
