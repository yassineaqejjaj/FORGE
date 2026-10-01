"""Human calibration of AI judges (docs/ARCHITECTURE.md §9.4).

Input: :class:`~forge.domain.types.ScorePair` — the normalised AI score (aggregate of the judges,
``judge_key=None``, or one judge's verdict) and the normalised human score of the same run and
criterion. Output, per judge and per criterion:

* ``n``; ``agreement_rate`` — share of pairs with ``|ai − human| ≤ 0.2``; ``mean_abs_error``;
  ``bias`` — mean of ``ai − human`` (positive: the AI is more lenient than humans);
* ``spearman`` / ``pearson`` correlations (≥ 3 non-constant points);
* ``kappa`` — Cohen's kappa with quadratic weights on scores mapped to integers 0–5;
* ``status`` — ``insufficient_data`` (n < 10), ``calibrated`` (κ ≥ 0.6 and agreement ≥ 0.7),
  ``weak`` (κ ≥ 0.4), ``uncalibrated`` otherwise.

The headline (``overall``) and the per-criterion breakdown use the aggregated AI score when
aggregate pairs are present (that is the score that enters the composite); individual judges are
reported in ``by_judge`` and ``by_judge_criterion``, never mixed with the aggregate.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from forge.domain.enums import CalibrationStatus
from forge.domain.stats import (
    DEFAULT_AGREEMENT_TOLERANCE,
    agreement_rate,
    mean,
    mean_absolute_error,
    pearson,
    quadratic_weighted_kappa,
    spearman,
    to_ordinal,
)
from forge.domain.types import ScorePair

MIN_PAIRS = 10
CALIBRATED_KAPPA = 0.6
CALIBRATED_AGREEMENT = 0.7
WEAK_KAPPA = 0.4
AGGREGATE_KEY = "aggregate"
AGGREGATE_LABEL = "Agrégat des juges"

STATUS_LABELS: dict[str, str] = {
    CalibrationStatus.calibrated: "Calibré",
    CalibrationStatus.weak: "Accord faible",
    CalibrationStatus.uncalibrated: "Non calibré",
    CalibrationStatus.insufficient_data: "Données insuffisantes",
}


@dataclass(slots=True)
class CalibrationMetrics:
    key: str
    label: str
    n: int
    agreement_rate: float | None
    mean_abs_error: float | None
    bias: float | None
    mean_ai: float | None
    mean_human: float | None
    spearman: float | None
    pearson: float | None
    kappa: float | None
    status: CalibrationStatus
    status_label: str
    judge_key: str | None = None
    criterion_key: str | None = None


@dataclass(slots=True)
class CalibrationReport:
    overall: CalibrationMetrics
    by_judge: list[CalibrationMetrics] = field(default_factory=list)
    by_criterion: list[CalibrationMetrics] = field(default_factory=list)
    by_judge_criterion: list[CalibrationMetrics] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)


def calibration_status(n: int, kappa: float | None, agreement: float | None) -> CalibrationStatus:
    if n < MIN_PAIRS:
        return CalibrationStatus.insufficient_data
    if (
        kappa is not None
        and agreement is not None
        and kappa >= CALIBRATED_KAPPA
        and agreement >= CALIBRATED_AGREEMENT
    ):
        return CalibrationStatus.calibrated
    if kappa is not None and kappa >= WEAK_KAPPA:
        return CalibrationStatus.weak
    return CalibrationStatus.uncalibrated


def calibration_metrics(
    pairs: Sequence[ScorePair],
    *,
    key: str,
    label: str,
    tolerance: float = DEFAULT_AGREEMENT_TOLERANCE,
    judge_key: str | None = None,
    criterion_key: str | None = None,
) -> CalibrationMetrics:
    ai = [float(p.ai) for p in pairs]
    human = [float(p.human) for p in pairs]
    agreement = agreement_rate(ai, human, tolerance=tolerance)
    kappa = quadratic_weighted_kappa([to_ordinal(v) for v in ai], [to_ordinal(v) for v in human])
    status = calibration_status(len(pairs), kappa, agreement)
    return CalibrationMetrics(
        key=key,
        label=label,
        n=len(pairs),
        agreement_rate=agreement,
        mean_abs_error=mean_absolute_error(ai, human),
        bias=mean(a - h for a, h in zip(ai, human, strict=True)),
        mean_ai=mean(ai),
        mean_human=mean(human),
        spearman=spearman(ai, human),
        pearson=pearson(ai, human),
        kappa=kappa,
        status=status,
        status_label=STATUS_LABELS[status],
        judge_key=judge_key,
        criterion_key=criterion_key,
    )


def _judge(pair: ScorePair) -> str:
    return pair.judge_key or AGGREGATE_KEY


def _judge_label(key: str) -> str:
    return AGGREGATE_LABEL if key == AGGREGATE_KEY else key


def _grouped(pairs: Sequence[ScorePair], key_fn: Callable[[ScorePair], str]) -> dict[str, list[ScorePair]]:
    groups: dict[str, list[ScorePair]] = defaultdict(list)
    for pair in pairs:
        groups[key_fn(pair)].append(pair)
    return dict(sorted(groups.items()))


def calibrate(
    pairs: Sequence[ScorePair],
    *,
    tolerance: float = DEFAULT_AGREEMENT_TOLERANCE,
    criterion_labels: dict[str, str] | None = None,
) -> CalibrationReport:
    """Calibration report of AI scores against human scores."""
    labels = criterion_labels or {}
    aggregate = [p for p in pairs if p.judge_key is None]
    headline = aggregate or list(pairs)
    if aggregate:
        overall_key, overall_label = AGGREGATE_KEY, AGGREGATE_LABEL
    else:
        judges = sorted({_judge(p) for p in pairs})
        overall_key = judges[0] if len(judges) == 1 else "all"
        overall_label = _judge_label(overall_key) if len(judges) == 1 else "Tous les juges"
    overall = calibration_metrics(
        headline,
        key=overall_key,
        label=overall_label,
        tolerance=tolerance,
        judge_key=None if overall_key in (AGGREGATE_KEY, "all") else overall_key,
    )
    by_judge = [
        calibration_metrics(
            members,
            key=key,
            label=_judge_label(key),
            tolerance=tolerance,
            judge_key=None if key == AGGREGATE_KEY else key,
        )
        for key, members in _grouped(pairs, _judge).items()
    ]
    by_criterion = [
        calibration_metrics(
            members, key=key, label=labels.get(key, key), tolerance=tolerance, criterion_key=key
        )
        for key, members in _grouped(headline, lambda p: p.criterion_key).items()
    ]
    by_judge_criterion = []
    for key, members in _grouped(pairs, lambda p: f"{_judge(p)}|{p.criterion_key}").items():
        judge_key, _, criterion_key = key.partition("|")
        by_judge_criterion.append(
            calibration_metrics(
                members,
                key=key,
                label=f"{_judge_label(judge_key)} — {labels.get(criterion_key, criterion_key)}",
                tolerance=tolerance,
                judge_key=None if judge_key == AGGREGATE_KEY else judge_key,
                criterion_key=criterion_key,
            )
        )
    return CalibrationReport(
        overall=overall,
        by_judge=by_judge,
        by_criterion=by_criterion,
        by_judge_criterion=by_judge_criterion,
        thresholds={
            "agreement_tolerance": tolerance,
            "min_pairs": MIN_PAIRS,
            "calibrated_kappa": CALIBRATED_KAPPA,
            "calibrated_agreement": CALIBRATED_AGREEMENT,
            "weak_kappa": WEAK_KAPPA,
        },
    )


__all__ = [
    "AGGREGATE_KEY",
    "MIN_PAIRS",
    "STATUS_LABELS",
    "CalibrationMetrics",
    "CalibrationReport",
    "calibrate",
    "calibration_metrics",
    "calibration_status",
]
