"""Human calibration of AI judges (docs/ARCHITECTURE.md §9.4).

Pairs are built per run × criterion from the ``evaluations`` table:

* **human** score: mean of the normalised human evaluations (``evaluator_kind=human``; several
  evaluators of the same run and criterion are averaged);
* **AI aggregate**: the ``scores`` row of source ``ai`` of the run's current round and own
  configuration (the score that enters the composite);
* **individual judges**: the ``llm_judge`` verdicts of the current round, keyed by
  ``"<judge key>@v<version>"``.

Filters: ``judge_id`` (only that judge version's verdicts), ``criterion_key``, ``dataset_id`` (a
gold dataset: only its runs). Runs above the viewer's clearance are ignored.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.calibration import calibrate
from forge.domain.enums import DatasetKind, EvaluatorKind, ScoreSource
from forge.domain.types import ScorePair, to_dict
from forge.infra.models import (
    Criterion,
    Dataset,
    DatasetItem,
    Evaluation,
    EvaluationRun,
    Judge,
    Scenario,
    Score,
)
from forge.services import access
from forge.services.access import Viewer
from forge.services.run_summaries import AnalyticsInvalid, AnalyticsNotFound

MAX_PAIRS_RETURNED = 500


async def _human_scores(
    session: AsyncSession, conditions: Sequence[ColumnElement[bool]]
) -> dict[tuple[uuid.UUID, str], float]:
    rows = await session.execute(
        select(Evaluation.run_id, Evaluation.criterion_key, func.avg(Evaluation.normalized_score))
        .join(EvaluationRun, EvaluationRun.id == Evaluation.run_id)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .where(Evaluation.evaluator_kind == EvaluatorKind.human, *conditions)
        .group_by(Evaluation.run_id, Evaluation.criterion_key)
    )
    return {(run_id, key): float(value) for run_id, key, value in rows.all()}


async def calibration_report(
    session: AsyncSession,
    viewer: Viewer,
    *,
    judge_id: uuid.UUID | None = None,
    criterion_key: str | None = None,
    dataset_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    conditions: list[ColumnElement[bool]] = [access.classification_condition(viewer)]
    judge: Judge | None = None
    if judge_id is not None:
        judge = await session.get(Judge, judge_id)
        if judge is None:
            raise AnalyticsNotFound("Juge introuvable")
    dataset: Dataset | None = None
    if dataset_id is not None:
        dataset = await session.get(Dataset, dataset_id)
        if dataset is None:
            raise AnalyticsNotFound("Jeu de données introuvable")
        if dataset.kind != DatasetKind.gold:
            raise AnalyticsInvalid("Ce jeu de données n'est pas un jeu gold (kind=gold attendu)")
        conditions.append(
            EvaluationRun.id.in_(
                select(DatasetItem.run_id).where(
                    DatasetItem.dataset_id == dataset_id, DatasetItem.run_id.is_not(None)
                )
            )
        )
    criterion_conditions: list[ColumnElement[bool]] = []
    if criterion_key:
        criterion_conditions.append(Evaluation.criterion_key == criterion_key)

    human = await _human_scores(session, [*conditions, *criterion_conditions])
    run_ids = list({run_id for run_id, _ in human})
    pairs: list[ScorePair] = []
    if run_ids:
        if judge is None:
            score_conditions = [Score.criterion_key == criterion_key] if criterion_key else []
            ai_rows = await session.execute(
                select(Score.run_id, Score.criterion_key, Score.value)
                .join(
                    EvaluationRun,
                    and_(
                        EvaluationRun.id == Score.run_id,
                        Score.round == EvaluationRun.evaluation_round,
                        Score.evaluation_config_id == EvaluationRun.evaluation_config_id,
                    ),
                )
                .where(Score.source == ScoreSource.ai, Score.run_id.in_(run_ids), *score_conditions)
            )
            for run_id, key, value in ai_rows.all():
                if (run_id, key) in human:
                    pairs.append(ScorePair(str(run_id), key, float(value), human[(run_id, key)], None))
        judge_conditions: list[ColumnElement[bool]] = [*criterion_conditions]
        if judge is not None:
            judge_conditions.append(Evaluation.judge_id == judge.id)
        judge_rows = await session.execute(
            select(
                Evaluation.run_id,
                Evaluation.criterion_key,
                Evaluation.evaluator_key,
                func.avg(Evaluation.normalized_score),
            )
            .join(
                EvaluationRun,
                and_(
                    EvaluationRun.id == Evaluation.run_id, Evaluation.round == EvaluationRun.evaluation_round
                ),
            )
            .where(
                Evaluation.evaluator_kind == EvaluatorKind.llm_judge,
                Evaluation.run_id.in_(run_ids),
                *judge_conditions,
            )
            .group_by(Evaluation.run_id, Evaluation.criterion_key, Evaluation.evaluator_key)
        )
        for run_id, key, judge_key, value in judge_rows.all():
            if (run_id, key) in human:
                pairs.append(ScorePair(str(run_id), key, float(value), human[(run_id, key)], str(judge_key)))
    pairs.sort(key=lambda p: (p.judge_key or "", p.criterion_key, p.run_id))
    labels = dict((await session.execute(select(Criterion.key, Criterion.name))).all())
    report = calibrate(pairs, criterion_labels=labels)
    return {
        "filters": {
            "judge_id": judge.id if judge else None,
            "judge": f"{judge.key}@v{judge.version}" if judge else None,
            "criterion_key": criterion_key,
            "dataset_id": dataset.id if dataset else None,
            "dataset": dataset.name if dataset else None,
        },
        "n_runs": len(run_ids),
        "n_human_scores": len(human),
        **to_dict(report),
        "pairs": [to_dict(p) for p in pairs[:MAX_PAIRS_RETURNED]],
        "pairs_truncated": len(pairs) > MAX_PAIRS_RETURNED,
    }
