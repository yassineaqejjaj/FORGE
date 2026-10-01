"""Human evaluations and the review queue (docs/ARCHITECTURE.md §7.1, §9.4).

* The **queue** lists completed runs the caller has not evaluated yet, ordered for active learning:
  strongest judge disagreement first (max ``scores.spread``), then lowest AI confidence.
* A **human evaluation** is one ``evaluations`` row per criterion (``evaluator_kind=human``,
  ``round=NULL`` — it applies to every round, ``evaluator_key=human:<user id>``). Submitting again
  replaces the caller's previous rows; the run is then re-scored without calling judges
  (``forge.services.evaluation.rescore_run``).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import and_, delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.defaults import DEFAULT_JUDGED_CRITERIA
from forge.domain.enums import Dimension, EvaluatorKind, RunStatus, ScenarioVisibility, ScoreSource
from forge.domain.redaction import redact_evaluation
from forge.domain.types import CriterionSpec
from forge.infra.models import Evaluation, EvaluationRun, Scenario, Score, User
from forge.services import access, audit
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.datasets import gold_run_ids
from forge.services.mapping import load_criteria_catalog
from forge.services.run_queries import get_visible_run, must_redact_run
from forge.services.taxonomy import ForbiddenError, InvalidError

logger = logging.getLogger("forge.reviews")

DEFAULT_EXPLANATION = "Évaluation humaine sans commentaire"
REVIEWABLE_STATUSES = (RunStatus.completed, RunStatus.failed)
#: Dimensions never scored by humans or judges (measured or group-level).
NON_JUDGED_DIMENSIONS = frozenset({Dimension.cost, Dimension.latency, Dimension.robustness})


def human_key(user_id: uuid.UUID) -> str:
    return f"human:{user_id}"


# =====================================================================================================
# Criteria applicable to a run
# =====================================================================================================


def _criterion_dict(c: CriterionSpec) -> dict[str, Any]:
    return {
        "key": c.key,
        "dimension": c.dimension.value if hasattr(c.dimension, "value") else str(c.dimension),
        "name": c.name,
        "question": c.question,
        "rubric": c.rubric,
        "scale_min": c.scale_min,
        "scale_max": c.scale_max,
    }


def review_criteria(manifest: dict[str, Any], catalog: dict[str, CriterionSpec]) -> list[dict[str, Any]]:
    """Criteria a human rates on a run: the scenario's criteria (default judged criteria otherwise)
    plus the configuration's, excluding measured dimensions."""
    result: dict[str, dict[str, Any]] = {}
    scenario_criteria = (manifest.get("scenario") or {}).get("criteria") or []
    for item in scenario_criteria:
        if isinstance(item, dict) and item.get("key"):
            result[item["key"]] = {
                k: item.get(k)
                for k in ("key", "dimension", "name", "question", "rubric", "scale_min", "scale_max")
            }
    if not result:
        for key in DEFAULT_JUDGED_CRITERIA:
            if key in catalog:
                result[key] = _criterion_dict(catalog[key])
    for item in (manifest.get("evaluation") or {}).get("criteria") or []:
        if isinstance(item, dict) and item.get("key") and item["key"] not in result:
            result[item["key"]] = {
                k: item.get(k)
                for k in ("key", "dimension", "name", "question", "rubric", "scale_min", "scale_max")
            }
    return [
        c for c in result.values() if str(c.get("dimension")) not in {d.value for d in NON_JUDGED_DIMENSIONS}
    ]


def _scale_for(
    key: str, manifest: dict[str, Any], catalog: dict[str, CriterionSpec]
) -> tuple[Dimension, float, float]:
    for source in (
        (manifest.get("scenario") or {}).get("criteria") or [],
        (manifest.get("evaluation") or {}).get("criteria") or [],
    ):
        for item in source:
            if isinstance(item, dict) and item.get("key") == key:
                base = catalog.get(key)
                dimension = item.get("dimension") or (base.dimension if base else key.split(".", 1)[0])
                return (
                    Dimension(dimension),
                    float(item.get("scale_min", base.scale_min if base else 0.0)),
                    float(item.get("scale_max", base.scale_max if base else 5.0)),
                )
    base = catalog.get(key)
    if base is None:
        raise InvalidError(f"Critère inconnu « {key} »")
    return Dimension(base.dimension), float(base.scale_min), float(base.scale_max)


# =====================================================================================================
# Queue
# =====================================================================================================


@dataclass(slots=True)
class QueueItem:
    run: EvaluationRun
    scenario: Scenario
    max_spread: float | None
    min_confidence: float | None
    ai_scores: dict[str, float]
    criteria: list[dict[str, Any]]


async def review_queue(
    session: AsyncSession,
    viewer: Viewer,
    user_id: uuid.UUID,
    *,
    dataset_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[QueueItem], int]:
    already = exists().where(
        Evaluation.run_id == EvaluationRun.id,
        Evaluation.evaluator_kind == EvaluatorKind.human,
        Evaluation.human_user_id == user_id,
    )
    conditions: list[Any] = [
        EvaluationRun.status == RunStatus.completed,
        access.classification_condition(viewer),
        ~already,
    ]
    if not viewer.can_see_private:
        conditions.append(Scenario.visibility != ScenarioVisibility.private)
        conditions.append(
            EvaluationRun.manifest[("scenario", "visibility")].astext != ScenarioVisibility.private.value
        )
    if dataset_id is not None:
        conditions.append(EvaluationRun.id.in_(await gold_run_ids(session, dataset_id) or [uuid.UUID(int=0)]))
    stats = (
        select(
            Score.run_id.label("run_id"),
            func.max(Score.spread).label("max_spread"),
            func.min(Score.confidence).label("min_confidence"),
        )
        .join(
            EvaluationRun,
            and_(EvaluationRun.id == Score.run_id, Score.round == EvaluationRun.evaluation_round),
        )
        .where(Score.source == ScoreSource.ai)
        .group_by(Score.run_id)
        .subquery()
    )
    base = (
        select(EvaluationRun, Scenario, stats.c.max_spread, stats.c.min_confidence)
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .outerjoin(stats, stats.c.run_id == EvaluationRun.id)
        .where(*conditions)
    )
    total = await session.scalar(
        select(func.count(EvaluationRun.id))
        .join(Scenario, Scenario.id == EvaluationRun.scenario_id)
        .where(*conditions)
    )
    rows = (
        await session.execute(
            base.order_by(
                stats.c.max_spread.desc().nulls_last(),
                stats.c.min_confidence.asc().nulls_last(),
                EvaluationRun.created_at.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    ).all()
    run_ids = [r[0].id for r in rows]
    ai: dict[uuid.UUID, dict[str, float]] = {rid: {} for rid in run_ids}
    if run_ids:
        for score in await session.scalars(
            select(Score)
            .join(
                EvaluationRun,
                and_(EvaluationRun.id == Score.run_id, Score.round == EvaluationRun.evaluation_round),
            )
            .where(Score.run_id.in_(run_ids), Score.source == ScoreSource.ai)
        ):
            ai[score.run_id][score.criterion_key] = score.value
    catalog = await load_criteria_catalog(session)
    items = [
        QueueItem(
            run,
            scenario,
            spread,
            confidence,
            ai.get(run.id, {}),
            review_criteria(run.manifest or {}, catalog),
        )
        for run, scenario, spread, confidence in rows
    ]
    return items, int(total or 0)


# =====================================================================================================
# Human evaluations
# =====================================================================================================


@dataclass(slots=True)
class HumanScore:
    criterion_key: str
    score: float
    comment: str | None = None


async def submit_human_evaluation(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    run_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None,
    scores: Sequence[HumanScore],
    comment: str | None = None,
) -> tuple[EvaluationRun, list[Evaluation], bool]:
    """Returns ``(run, rows, rescored)``."""
    if user_id is None:
        raise ForbiddenError("Les évaluations humaines sont réservées aux utilisateurs (pas aux clés d'API)")
    run, scenario = await get_visible_run(session, viewer, run_id)
    if must_redact_run(viewer, run, scenario):
        raise ForbiddenError("Évaluation impossible : le contenu de ce scénario privé vous est masqué")
    if run.status not in REVIEWABLE_STATUSES:
        raise InvalidError("Seuls les runs terminés (completed ou failed) peuvent être évalués")
    if not scores:
        raise InvalidError("Au moins un score est requis")
    keys = [s.criterion_key for s in scores]
    if len(set(keys)) != len(keys):
        raise InvalidError("Chaque critère ne peut être noté qu'une fois")
    catalog = await load_criteria_catalog(session)
    manifest = run.manifest or {}
    general = (comment or "").strip()
    rows: list[Evaluation] = []
    for item in scores:
        dimension, smin, smax = _scale_for(item.criterion_key, manifest, catalog)
        if dimension in NON_JUDGED_DIMENSIONS:
            raise InvalidError(f"Le critère « {item.criterion_key} » est mesuré automatiquement")
        if not smin <= item.score <= smax:
            raise InvalidError(f"Score de « {item.criterion_key} » hors échelle ({smin:g} à {smax:g})")
        span = smax - smin
        rows.append(
            Evaluation(
                run_id=run.id,
                round=None,
                evaluation_config_id=run.evaluation_config_id,
                evaluator_kind=EvaluatorKind.human,
                evaluator_key=human_key(user_id),
                criterion_key=item.criterion_key,
                dimension=dimension,
                raw_score=float(item.score),
                scale_min=smin,
                scale_max=smax,
                normalized_score=min(1.0, max(0.0, (item.score - smin) / span)) if span > 0 else 0.0,
                confidence=1.0,
                explanation=(item.comment or "").strip() or general or DEFAULT_EXPLANATION,
                human_user_id=user_id,
            )
        )
    replaced = await session.execute(
        delete(Evaluation)
        .where(
            Evaluation.run_id == run.id,
            Evaluation.evaluator_kind == EvaluatorKind.human,
            Evaluation.human_user_id == user_id,
        )
        .returning(Evaluation.id)
    )
    replaced_count = len(replaced.all())
    session.add_all(rows)
    await session.flush()
    await audit.record(
        session,
        actor,
        "human_evaluation.submit",
        "evaluation_run",
        run.id,
        summary=f"Évaluation humaine du run ({len(rows)} critère(s))",
        details={"criteria": {r.criterion_key: r.raw_score for r in rows}, "replaced": replaced_count},
    )
    rescored = False
    if run.evaluation_round > 0:
        from forge.services import evaluation as evaluation_service

        try:
            await evaluation_service.rescore_run(session, run)
            rescored = True
        except NotImplementedError:
            logger.info("rescore_run not available yet: human evaluation stored without re-scoring")
    return run, rows, rescored


async def list_human_evaluations(
    session: AsyncSession, viewer: Viewer, run_id: uuid.UUID
) -> list[dict[str, Any]]:
    run, scenario = await get_visible_run(session, viewer, run_id)
    redact = must_redact_run(viewer, run, scenario)
    rows = (
        await session.execute(
            select(Evaluation, User.full_name)
            .outerjoin(User, User.id == Evaluation.human_user_id)
            .where(Evaluation.run_id == run.id, Evaluation.evaluator_kind == EvaluatorKind.human)
            .order_by(Evaluation.created_at, Evaluation.criterion_key)
        )
    ).all()
    result = []
    for evaluation, name in rows:
        data = {
            "id": evaluation.id,
            "run_id": evaluation.run_id,
            "user_id": evaluation.human_user_id,
            "user_name": name,
            "evaluator_key": evaluation.evaluator_key,
            "criterion_key": evaluation.criterion_key,
            "dimension": evaluation.dimension,
            "score": evaluation.raw_score,
            "scale_min": evaluation.scale_min,
            "scale_max": evaluation.scale_max,
            "normalized_score": evaluation.normalized_score,
            "explanation": evaluation.explanation,
            "created_at": evaluation.created_at,
            "redacted": False,
        }
        if redact:
            data = redact_evaluation({**data, "evidence": [], "errors": []})
            data.pop("evidence", None)
            data.pop("errors", None)
            data.pop("raw_response", None)
        result.append(data)
    return result
