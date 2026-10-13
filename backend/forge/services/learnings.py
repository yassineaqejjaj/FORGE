"""Publish a winning experiment to ORBIT as a validated learning (FORGE → ORBIT).

An improvement is only worth keeping if it held up: the experiment must be completed, recommended by its own
comparison, free of critical regressions and — when it was one candidate among several — the winner *after*
the multiple-comparison correction. The evidence sent to ORBIT is computed here from the comparison (the
caller cannot inflate it). ORBIT stores the learning as a proposal for human validation, with its scope of
application; FORGE keeps the ORBIT item id as a tag so publishing twice is a no-op.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.classification import MAX_LEVEL
from forge.domain.enums import ExecutionStatus, ExperimentArm, Recommendation
from forge.infra.models import AgentVersion, EvaluationRun, Experiment, Scenario, ScenarioVersion
from forge.services import audit, multi_experiments, promotion
from forge.services import experiments as experiment_service
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.benchmarks import agent_version_labels
from forge.services.context_providers import ContextPreparationError, call_orbit, orbit_config_for
from forge.services.run_summaries import AnalyticsConflict, AnalyticsInvalid

TAG_PREFIX = "learning:"
SHIPPABLE = {Recommendation.ship.value, Recommendation.ship_with_caution.value}
MAX_RUN_IDS = 50


@dataclass(slots=True)
class PublishRequest:
    title: str | None = None
    content: str | None = None
    applies_to: dict[str, Any] = field(default_factory=dict)
    orbit_project: str | None = None
    credential_id: uuid.UUID | None = None
    classification: int | None = None


@dataclass(slots=True)
class PublishResult:
    experiment_id: uuid.UUID
    orbit_item_id: str
    orbit_project: str
    created: bool
    learning: dict[str, Any] | None = None


def published_item_id(experiment: Experiment) -> str | None:
    for tag in experiment.tags or []:
        if isinstance(tag, str) and tag.startswith(TAG_PREFIX):
            return tag[len(TAG_PREFIX) :]
    return None


async def _require_winner(session: AsyncSession, viewer: Viewer, experiment: Experiment) -> None:
    """A candidate of a multi-candidate group is only publishable if it won the group after correction."""
    for tag in experiment.tags or []:
        if isinstance(tag, str) and tag.startswith("multi:"):
            report = await multi_experiments.multi_report(session, viewer, uuid.UUID(tag[len("multi:") :]))
            winner = report.get("winner")
            if winner is None or winner["experiment_id"] != experiment.id:
                raise AnalyticsInvalid(
                    "Cette candidate n'est pas le vainqueur de sa comparaison multiple (après correction)"
                )


async def _scenarios_level(session: AsyncSession, experiment: Experiment) -> int:
    """Highest classification among the scenarios the experiment ran (C3 when none is found)."""
    level = await session.scalar(
        select(func.max(Scenario.classification))
        .select_from(EvaluationRun)
        .join(ScenarioVersion, ScenarioVersion.id == EvaluationRun.scenario_version_id)
        .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
        .where(EvaluationRun.experiment_id == experiment.id)
    )
    return int(level) if level is not None else MAX_LEVEL


def _default_content(experiment: Experiment, candidate: AgentVersion | None, summary: str | None) -> str:
    parts = [
        experiment.hypothesis.strip(),
        (candidate.changelog or "").strip() if candidate else "",
        (summary or "").strip(),
    ]
    return "\n\n".join(p for p in parts if p)[:20000]


async def publish_learning(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    experiment_id: uuid.UUID,
    request: PublishRequest,
) -> PublishResult:
    experiment = await experiment_service.get_experiment(session, experiment_id)
    existing = published_item_id(experiment)
    if existing:
        return PublishResult(experiment.id, existing, "", created=False)
    if experiment.status != ExecutionStatus.completed:
        raise AnalyticsConflict("L'expérience n'est pas terminée : rien à publier")
    comparison = await experiment_service.experiment_comparison(session, viewer, experiment)
    if comparison.get("restricted"):
        raise AnalyticsConflict("Comparaison partielle (scénarios hors habilitation) : publication refusée")
    recommendation = (comparison.get("recommendation") or {}).get("recommendation")
    if recommendation not in SHIPPABLE:
        raise AnalyticsInvalid("Seule une expérience recommandée (ship) peut devenir un apprentissage")
    if any(r.get("severity") == "critical" for r in comparison.get("regressions") or []):
        raise AnalyticsInvalid("Une régression critique empêche de publier cet apprentissage")
    await _require_winner(session, viewer, experiment)
    # Strict policy: the CI gate must pass (ship only, judges calibrated, no contamination, regression
    # cases replayed). Under ``warn`` the findings are only recorded in the audit trail.
    promotion_findings: list[str] = []
    if promotion.policy_of() == "strict":
        gate = await experiment_service.experiment_gate(session, viewer, experiment)
        if not gate["passed"]:
            raise AnalyticsInvalid(
                "Publication refusée par la politique de promotion : " + " ".join(gate["reasons"])
            )
    else:
        promotion_findings = await promotion.experiment_problems(session, experiment)

    baseline_mean = (comparison.get("baseline") or {}).get("composite_mean")
    candidate_mean = (comparison.get("candidate") or {}).get("composite_mean")
    n_scored = (comparison.get("candidate") or {}).get("n_scored") or 0
    if baseline_mean is None or candidate_mean is None:
        raise AnalyticsInvalid("Comparaison sans score composite : publication impossible")
    run_ids = [
        str(r)
        for r in await session.scalars(
            select(EvaluationRun.id)
            .where(EvaluationRun.experiment_id == experiment.id, EvaluationRun.arm == ExperimentArm.candidate)
            .limit(MAX_RUN_IDS)
        )
    ]
    candidate = await session.get(AgentVersion, experiment.candidate_version_id)
    labels = await agent_version_labels(session, [experiment.candidate_version_id])
    label = (labels.get(experiment.candidate_version_id) or {}).get("label") or "candidate"
    evidence = {
        "source": "forge",
        "experiment_id": str(experiment.id),
        "eval_suite_id": str(experiment.benchmark_id) if experiment.benchmark_id else None,
        "run_ids": run_ids,
        "runs": int(n_scored),
        "metric": "composite",
        "baseline": float(baseline_mean),
        "candidate": float(candidate_mean),
    }
    content = request.content or _default_content(
        experiment, candidate, (comparison.get("recommendation") or {}).get("summary")
    )
    if not content:
        raise AnalyticsInvalid("Aucun contenu à publier : précisez `content`")
    payload: dict[str, Any] = {
        "title": (request.title or f"Amélioration validée : {label}")[:300],
        "content": content,
        "applies_to": request.applies_to,
        "evidence": {k: v for k, v in evidence.items() if v is not None},
    }
    # The text comes from hypotheses, changelogs and summaries of scenarios that may be C2/C3: ORBIT must
    # never apply its own default, and the level can only be raised by the caller.
    floor = await _scenarios_level(session, experiment)
    if request.classification is not None and request.classification < floor:
        raise AnalyticsInvalid(
            f"Classification inférieure à celle des scénarios (C{floor}) : publication refusée"
        )
    payload["classification"] = request.classification if request.classification is not None else floor

    agent_context = {}
    if candidate is not None:
        agent_context = dict(specs_from_manifest_agent(candidate).get("context_config") or {})
    orbit_cfg = dict(agent_context.get("orbit") or {})
    orbit_cfg["project"] = request.orbit_project or orbit_cfg.get("project")
    if request.credential_id:
        orbit_cfg["credential_id"] = str(request.credential_id)
    if not orbit_cfg.get("project"):
        raise AnalyticsInvalid("Projet ORBIT inconnu : précisez `orbit_project`")
    try:
        orbit = await orbit_config_for(session, {"orbit": orbit_cfg})
        item = await call_orbit(
            orbit, "POST", f"/api/v1/projects/{quote(orbit.project, safe='')}/learnings", payload=payload
        )
    except ContextPreparationError as exc:
        raise AnalyticsConflict(str(exc)) from exc
    item_id = str(item.get("id") or "")
    if not item_id:
        raise AnalyticsConflict("Réponse d'ORBIT inattendue : identifiant de l'apprentissage absent")
    experiment.tags = [*(experiment.tags or []), f"{TAG_PREFIX}{item_id}"]
    await session.flush()
    await audit.record(
        session,
        actor,
        "experiment.publish_learning",
        "experiment",
        experiment.id,
        summary=f"Apprentissage publié dans ORBIT ({orbit.project}) : {payload['title']}",
        details={
            "orbit_item_id": item_id,
            "orbit_project": orbit.project,
            "evidence": payload["evidence"],
            "promotion_warnings": promotion_findings,
        },
    )
    return PublishResult(experiment.id, item_id, orbit.project, created=True, learning=item)


def specs_from_manifest_agent(version: AgentVersion) -> dict[str, Any]:
    """The version's context configuration (where its ORBIT project and credential are configured)."""
    return {"context_config": dict(version.context_config or {})}
