"""Schemas of the calibration API (docs/ARCHITECTURE.md §9.4)."""

from __future__ import annotations

import uuid

from forge.api.schemas.common import ApiModel
from forge.domain.enums import CalibrationStatus


class CalibrationMetricsOut(ApiModel):
    key: str
    label: str
    n: int
    agreement_rate: float | None = None
    mean_abs_error: float | None = None
    bias: float | None = None
    mean_ai: float | None = None
    mean_human: float | None = None
    spearman: float | None = None
    pearson: float | None = None
    kappa: float | None = None
    status: CalibrationStatus
    status_label: str
    judge_key: str | None = None
    criterion_key: str | None = None


class CalibrationFiltersOut(ApiModel):
    judge_id: uuid.UUID | None = None
    judge: str | None = None
    criterion_key: str | None = None
    dataset_id: uuid.UUID | None = None
    dataset: str | None = None


class ScorePairOut(ApiModel):
    run_id: str
    criterion_key: str
    ai: float
    human: float
    judge_key: str | None = None


class CalibrationOut(ApiModel):
    filters: CalibrationFiltersOut
    n_runs: int
    n_human_scores: int
    overall: CalibrationMetricsOut
    by_judge: list[CalibrationMetricsOut]
    by_criterion: list[CalibrationMetricsOut]
    by_judge_criterion: list[CalibrationMetricsOut]
    thresholds: dict[str, float]
    pairs: list[ScorePairOut]
    pairs_truncated: bool
