"""Human calibration metrics and status (§9.4)."""

from __future__ import annotations

import pytest

from forge.domain.calibration import calibrate, calibration_metrics, calibration_status
from forge.domain.enums import CalibrationStatus
from forge.domain.types import ScorePair


def _pairs(
    values: list[tuple[float, float]], *, judge: str | None = None, criterion: str = "quality.accuracy"
):
    return [
        ScorePair(run_id=f"r{i}", criterion_key=criterion, ai=a, human=h, judge_key=judge)
        for i, (a, h) in enumerate(values)
    ]


def test_status_thresholds() -> None:
    assert calibration_status(9, 1.0, 1.0) == CalibrationStatus.insufficient_data
    assert calibration_status(10, 0.6, 0.7) == CalibrationStatus.calibrated
    assert calibration_status(10, 0.65, 0.6) == CalibrationStatus.weak
    assert calibration_status(10, 0.4, 0.9) == CalibrationStatus.weak
    assert calibration_status(10, 0.39, 0.9) == CalibrationStatus.uncalibrated
    assert calibration_status(10, None, None) == CalibrationStatus.uncalibrated


def test_well_calibrated_judge() -> None:
    values = [(i / 11, min(1.0, i / 11 + 0.05)) for i in range(12)]
    metrics = calibration_metrics(_pairs(values), key="k", label="k")
    assert metrics.n == 12
    assert metrics.agreement_rate == 1.0
    assert metrics.bias == pytest.approx(-0.05, abs=0.01)
    assert metrics.spearman == pytest.approx(1.0)
    assert metrics.kappa is not None and metrics.kappa > 0.9
    assert metrics.status == CalibrationStatus.calibrated
    assert metrics.status_label == "Calibré"


def test_lenient_judge_is_uncalibrated() -> None:
    values = [(1.0, h / 10) for h in range(11)]
    metrics = calibration_metrics(_pairs(values), key="k", label="k")
    assert metrics.bias is not None and metrics.bias > 0.4
    assert metrics.spearman is None  # constant AI score
    assert metrics.status == CalibrationStatus.uncalibrated


def test_report_breakdowns() -> None:
    aggregate = _pairs([(0.8, 0.8)] * 10) + _pairs([(0.2, 0.3)] * 3, criterion="ux.clarity")
    judge_a = _pairs([(0.9, 0.8)] * 10, judge="judge-a@v1")
    judge_b = _pairs([(0.1, 0.8)] * 10, judge="judge-b@v1")
    report = calibrate(aggregate + judge_a + judge_b, criterion_labels={"ux.clarity": "Clarté"})
    assert report.overall.key == "aggregate" and report.overall.n == 13
    assert [j.key for j in report.by_judge] == ["aggregate", "judge-a@v1", "judge-b@v1"]
    assert report.by_judge[2].agreement_rate == 0.0
    assert {c.key: c.n for c in report.by_criterion} == {"quality.accuracy": 10, "ux.clarity": 3}
    assert next(c for c in report.by_criterion if c.key == "ux.clarity").label == "Clarté"
    assert len(report.by_judge_criterion) == 4
    assert report.thresholds["min_pairs"] == 10


def test_report_single_judge_and_empty() -> None:
    report = calibrate(_pairs([(0.5, 0.5)] * 3, judge="j@v1"))
    assert report.overall.key == "j@v1" and report.overall.judge_key == "j@v1"
    assert report.overall.status == CalibrationStatus.insufficient_data
    empty = calibrate([])
    assert empty.overall.n == 0 and empty.overall.kappa is None and empty.by_judge == []
