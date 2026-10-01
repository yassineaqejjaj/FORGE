"""Experiment comparison (§9.3): verdicts, regressions, errors, resources, recommendation, gate."""

from __future__ import annotations

import json

import numpy as np
import pytest

from forge.domain.enums import ExperimentArm, Recommendation, RegressionSeverity, Verdict
from forge.domain.experiments import compare, evaluate_gate, metric_verdict, scenario_change
from forge.domain.types import to_dict
from tests.unit.analytics_builders import make_run


def _arms(
    deltas: list[float],
    *,
    reps: int = 1,
    noise: float = 0.0,
    base: float = 70.0,
    safety_delta: float = 0.0,
    seed: int = 7,
    cand_kwargs: dict[int, dict] | None = None,
    cost_ratio: float = 1.0,
) -> tuple[list, list]:
    rng = np.random.default_rng(seed)
    baseline, candidate = [], []
    for i, delta in enumerate(deltas):
        for rep in range(reps):
            b = float(np.clip(base + (i % 5) * 3 + rng.normal(0, noise), 0, 100))
            c = float(np.clip(b + delta + rng.normal(0, noise), 0, 100))
            baseline.append(
                make_run(
                    scenario=f"s{i}", agent="P", version="1.2", composite=b, repetition=rep,
                    dimensions={"quality": b / 100, "safety": 0.9}, arm=ExperimentArm.baseline,
                    cost=0.02, latency_ms=2000,
                )
            )  # fmt: skip
            extra = (cand_kwargs or {}).get(i, {})
            candidate.append(
                make_run(
                    scenario=f"s{i}",
                    agent="P",
                    version="1.3",
                    composite=extra.pop("composite", c),
                    repetition=rep,
                    dimensions={"quality": c / 100, "safety": min(1.0, 0.9 + safety_delta / 100)},
                    arm=ExperimentArm.candidate,
                    cost=0.02 * cost_ratio,
                    latency_ms=2000,
                    **extra,
                )
            )
    return baseline, candidate


def test_metric_verdict_rules() -> None:
    assert metric_verdict(None, None, None, None, 0) == Verdict.inconclusive
    assert metric_verdict(5.0, 2.0, 8.0, 0.01, 1) == Verdict.inconclusive  # one pair
    assert metric_verdict(1.0, -1.0, 3.0, 0.4, 20) == Verdict.equivalent
    assert metric_verdict(1.5, 0.5, 2.5, 0.001, 30) == Verdict.equivalent  # significant but negligible
    assert metric_verdict(6.0, 3.0, 9.0, 0.002, 12) == Verdict.better
    assert metric_verdict(-6.0, -9.0, -3.0, 0.002, 12) == Verdict.worse
    assert metric_verdict(6.0, 3.0, 9.0, 0.08, 5) == Verdict.inconclusive  # Wilcoxon not significant
    assert metric_verdict(1.0, -6.0, 8.0, 0.6, 12) == Verdict.inconclusive  # too wide for equivalence


def test_clear_improvement_is_shipped() -> None:
    baseline, candidate = _arms([8.0] * 12, reps=2, noise=1.0)
    result = compare(baseline, candidate, n_resamples=2000)
    assert result.n_pairs == 12 and result.n_unpaired == 0
    assert result.composite.verdict == Verdict.better
    assert result.composite.delta == pytest.approx(8.0, abs=1.0)
    assert result.composite.ci_low > 0 and result.composite.p_value < 0.01
    assert result.composite.delta_pct == pytest.approx(result.composite.delta / result.composite.baseline_mean * 100)
    quality = next(d for d in result.dimensions if d.key == "quality")
    assert quality.verdict == Verdict.better
    assert result.regressions == []
    assert len(result.improvements) == 12
    assert result.recommendation.recommendation == Recommendation.ship
    assert result.recommendation.confidence == "medium"
    assert result.recommendation.summary.startswith("Déploiement recommandé : P v1.3")
    assert "points" in result.recommendation.summary
    assert result.baseline.agent_label == "P v1.2" and result.candidate.agent_label == "P v1.3"


def test_clear_degradation_is_blocked() -> None:
    baseline, candidate = _arms([-9.0] * 10, reps=1)
    result = compare(baseline, candidate, n_resamples=2000)
    assert result.composite.verdict == Verdict.worse
    assert result.recommendation.recommendation == Recommendation.do_not_ship
    assert result.recommendation.summary.startswith("Déploiement déconseillé")
    # K = 1: the per-scenario threshold is max(5, 2 × 5) = 10 points, so −9 stays within the noise band
    # even though the paired test shows a systematic degradation.
    assert result.regressions == []


def test_default_noise_with_single_repetition() -> None:
    baseline, candidate = _arms([-9.0, -11.0, -16.0, 0.0], reps=1)
    result = compare(baseline, candidate, n_resamples=500)
    by_slug = {s.slug: s for s in result.scenarios}
    # K = 1: σ defaults to 5 points → threshold max(5, 10) = 10.
    assert by_slug["s0"].noise_std == 5.0 and by_slug["s0"].noise_estimated is False
    assert by_slug["s0"].threshold == 10.0
    assert by_slug["s0"].status == "stable"
    assert by_slug["s1"].status == "regression" and by_slug["s1"].severity == RegressionSeverity.major
    assert by_slug["s2"].severity == RegressionSeverity.critical
    assert by_slug["s3"].status == "stable"
    assert [r.slug for r in result.regressions] == ["s2", "s1"]
    assert any("Une seule répétition" in w for w in result.warnings)


def test_noise_estimated_from_repetitions() -> None:
    baseline = [make_run(scenario="x", composite=v, repetition=i) for i, v in enumerate([70.0, 74.0, 66.0])]
    candidate = [make_run(scenario="x", composite=v, repetition=i) for i, v in enumerate([62.0, 60.0, 64.0])]
    change = scenario_change(baseline, candidate)
    # pooled SS: baseline (16+16+0... ) → variances 16 and 4 with 2 dof each → σ = sqrt((32 + 8) / 4)
    assert change.noise_estimated is True
    assert change.noise_std == pytest.approx(np.sqrt(10.0))
    assert change.threshold == pytest.approx(max(5.0, 2 * np.sqrt(10.0)))
    assert change.delta == pytest.approx(-8.0)
    assert change.status == "regression" and change.severity == RegressionSeverity.minor


def test_new_gate_failure_is_critical_even_within_noise() -> None:
    baseline, candidate = _arms(
        [6.0] * 12, reps=1, cand_kwargs={3: {"composite": 72.0, "gate_failed": True, "passed": False}}
    )
    result = compare(baseline, candidate, n_resamples=1000)
    assert result.composite.verdict == Verdict.better
    critical = [r for r in result.regressions if r.severity == RegressionSeverity.critical]
    assert [r.slug for r in critical] == ["s3"]
    assert any("garde-fou" in reason for reason in critical[0].reasons)
    assert result.recommendation.recommendation == Recommendation.do_not_ship
    assert result.recommendation.confidence in ("medium", "high")


def test_new_critical_error_and_error_changes() -> None:
    baseline, candidate = _arms(
        [0.0] * 6,
        cand_kwargs={0: {"errors": [("DATA_LEAK", "critical")]}, 1: {"errors": [("FORMAT_ERROR", "low")]}},
    )
    baseline[2].errors = [("HALLUCINATION", "high")]
    result = compare(baseline, candidate, n_resamples=500)
    assert result.errors.appeared == ["DATA_LEAK", "FORMAT_ERROR"]
    assert result.errors.disappeared == ["HALLUCINATION"]
    change = {c.error_type: c for c in result.errors.changes}
    assert change["DATA_LEAK"].candidate_rate == pytest.approx(1 / 6)
    assert change["DATA_LEAK"].max_severity == "critical"
    s0 = next(s for s in result.scenarios if s.slug == "s0")
    assert s0.status == "regression" and s0.new_critical_errors == ["DATA_LEAK"]
    assert result.recommendation.recommendation == Recommendation.do_not_ship


def test_equivalent_without_gain_is_inconclusive_and_with_gain_is_caution() -> None:
    deltas = [0.5, -0.5, 0.3, -0.2, 0.1, 0.0, 0.4, -0.3, 0.2, -0.1, 0.0, 0.3]
    baseline, candidate = _arms(deltas)
    result = compare(baseline, candidate, n_resamples=1000)
    assert result.composite.verdict == Verdict.equivalent
    assert result.recommendation.recommendation == Recommendation.inconclusive
    assert result.recommendation.summary.startswith("Pas de différence démontrée")
    baseline, candidate = _arms(deltas, cost_ratio=0.5)
    cheaper = compare(baseline, candidate, n_resamples=1000)
    cost = next(r for r in cheaper.resources if r.key == "cost")
    assert cost.relative_change == pytest.approx(-0.5) and cost.assessment == "gain"
    assert cheaper.recommendation.recommendation == Recommendation.ship_with_caution
    assert "efficacité" in cheaper.recommendation.summary


def test_better_with_cost_increase_is_caution() -> None:
    baseline, candidate = _arms([8.0] * 10, cost_ratio=1.5)
    result = compare(baseline, candidate, n_resamples=1000)
    assert result.composite.verdict == Verdict.better
    assert result.recommendation.recommendation == Recommendation.ship_with_caution
    assert "coût moyen par run +50" in result.recommendation.summary


def test_safety_worse_blocks() -> None:
    baseline, candidate = _arms([4.0] * 10, safety_delta=-20.0)
    for i, run in enumerate(candidate):  # vary the safety drop so the Wilcoxon test has ranks
        run.dimensions["safety"] = 0.7 - i * 0.005
    result = compare(baseline, candidate, n_resamples=1000)
    safety = next(d for d in result.dimensions if d.key == "safety")
    assert safety.verdict == Verdict.worse
    assert result.recommendation.recommendation == Recommendation.do_not_ship
    assert "sécurité" in result.recommendation.summary


def test_small_experiment_is_inconclusive() -> None:
    baseline, candidate = _arms([10.0, 12.0, 9.0])
    result = compare(baseline, candidate, n_resamples=1000)
    assert result.composite.verdict == Verdict.inconclusive
    assert result.recommendation.recommendation == Recommendation.inconclusive
    assert result.recommendation.confidence == "low"


def test_unpaired_scenarios_and_cancelled_runs() -> None:
    baseline, candidate = _arms([5.0] * 4)
    candidate[0].status = "cancelled"
    candidate[0].composite = None
    result = compare(baseline, candidate, n_resamples=500)
    assert result.n_pairs == 3 and result.n_unpaired == 1
    assert next(s for s in result.scenarios if s.slug == "s0").status == "unpaired"
    assert result.candidate.n_cancelled == 1
    assert any("exclu" in w for w in result.warnings)


def test_no_pairs() -> None:
    result = compare([], [], n_resamples=100)
    assert result.n_pairs == 0
    assert result.recommendation.recommendation == Recommendation.inconclusive
    assert "aucun scénario" in result.recommendation.summary


def test_comparison_is_deterministic_and_json_ready() -> None:
    baseline, candidate = _arms([3.0, -2.0, 7.0, 1.0, 4.0, 6.0, -1.0, 5.0], reps=2, noise=2.0)
    first = json.dumps(to_dict(compare(baseline, candidate)), sort_keys=True)
    second = json.dumps(to_dict(compare(baseline, candidate)), sort_keys=True)
    assert first == second


def test_gate() -> None:
    regressions = [
        {"name": "Scénario B", "delta": -12.0, "severity": "major", "reasons": ["Score composite −12,0 points"]},
        {"name": "Scénario A", "delta": -20.0, "severity": "critical", "reasons": []},
    ]
    gate = evaluate_gate(status="completed", recommendation="do_not_ship", regressions=regressions, summary="Résumé")
    assert gate.passed is False
    assert gate.reasons[0].startswith("Garde-fou CI bloquant")
    assert gate.reasons[2].startswith("Régression critique sur « Scénario A »")
    assert evaluate_gate(status="completed", recommendation="inconclusive").passed is True
    assert evaluate_gate(status="completed", recommendation="inconclusive", strict=True).passed is False
    assert evaluate_gate(status="completed", recommendation="ship", strict=True).passed is True
    running = evaluate_gate(status="running", recommendation=None)
    assert running.passed is False and "en cours" in running.reasons[0]
    assert evaluate_gate(status="completed", recommendation=None).passed is False
