"""Promotion policy: what must hold before an experiment starts, passes the CI gate or becomes a learning.

``FORGE_PROMOTION_POLICY`` = ``strict`` (default) blocks, ``warn`` only reports the same findings:

* every judge of the evaluation configuration is **calibrated** against human scores on gold datasets
  (n ≥ ``MIN_PAIRS``, weighted κ ≥ ``FORGE_CALIBRATION_MIN_KAPPA``, agreement ≥ ``CALIBRATED_AGREEMENT``);
* the compared agent versions carry **no contamination** warning (canaries / private expected outputs);
* the **regression cases** of the agent (scenarios promoted from its failed runs) are replayed by the
  experiment.

Each check returns French messages; callers decide with :func:`enforce` whether they block.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.calibration import CALIBRATED_AGREEMENT, MIN_PAIRS
from forge.infra.models import (
    AgentVersion,
    EvaluationConfig,
    EvaluationRun,
    Experiment,
    ExperimentScenario,
    Judge,
    Scenario,
)
from forge.services import calibration
from forge.services.run_summaries import AnalyticsInvalid

REGRESSION_TAG = "regression"
FROM_RUN_PREFIX = "from-run:"


@dataclass(frozen=True, slots=True)
class _Unrestricted:
    """Viewer of system checks: calibration is measured on every gold run, whatever its clearance."""

    clearance: int = 3
    can_see_private: bool = False


def policy_of(override: str | None = None) -> str:
    return override or settings.promotion_policy


def enforce(problems: Sequence[str], *, policy: str | None = None, what: str) -> list[str]:
    """Raise under the strict policy, else return ``problems`` as warnings."""
    if problems and policy_of(policy) == "strict":
        raise AnalyticsInvalid(f"{what} : " + " ; ".join(problems))
    return list(problems)


async def judge_problems(session: AsyncSession, config: EvaluationConfig) -> list[str]:
    """Judges of ``config`` that are not calibrated on a gold set."""
    problems: list[str] = []
    for raw in config.judge_ids or []:
        judge = await session.get(Judge, uuid.UUID(str(raw)))
        if judge is None:
            problems.append(f"Juge {raw} introuvable")
            continue
        report = await calibration.calibration_report(
            session, _Unrestricted(), judge_id=judge.id, gold_only=True
        )
        overall = report["overall"]
        n, kappa, agreement = overall["n"], overall["kappa"], overall["agreement_rate"]
        if (
            n >= MIN_PAIRS
            and kappa is not None
            and kappa >= settings.calibration_min_kappa
            and (agreement or 0.0) >= CALIBRATED_AGREEMENT
        ):
            continue
        measured = "aucune mesure" if not n else f"n={n}, κ={'?' if kappa is None else f'{kappa:.2f}'}"
        problems.append(
            f"Juge {judge.key}@v{judge.version} non calibré sur un jeu gold ({measured} ; "
            f"requis : n ≥ {MIN_PAIRS}, κ ≥ {settings.calibration_min_kappa:g}, "
            f"accord ≥ {CALIBRATED_AGREEMENT:g})"
        )
    return problems


async def contamination_problems(session: AsyncSession, version_ids: Sequence[uuid.UUID]) -> list[str]:
    rows = await session.execute(
        select(AgentVersion.id, AgentVersion.version, AgentVersion.contamination).where(
            AgentVersion.id.in_(list(version_ids))
        )
    )
    return [
        f"Version d'agent v{version} : contamination détectée ({len(found)} alerte(s))"
        for _, version, found in rows.all()
        if found
    ]


async def regression_case_problems(session: AsyncSession, experiment: Experiment) -> list[str]:
    """Regression scenarios of the candidate's agent that the experiment does not replay."""
    agent_id = await session.scalar(
        select(AgentVersion.agent_id).where(AgentVersion.id == experiment.candidate_version_id)
    )
    if agent_id is None:
        return []
    tagged = (
        await session.execute(
            select(Scenario.id, Scenario.tags).where(
                Scenario.tags.contains([REGRESSION_TAG]), Scenario.archived.is_(False)
            )
        )
    ).all()
    run_of = {
        scenario_id: tag.removeprefix(FROM_RUN_PREFIX)
        for scenario_id, tags in tagged
        for tag in tags or []
        if isinstance(tag, str) and tag.startswith(FROM_RUN_PREFIX)
    }
    if not run_of:
        return []
    owned = {
        str(run_id)
        for run_id in await session.scalars(
            select(EvaluationRun.id).where(EvaluationRun.agent_id == agent_id)
        )
    }
    cases = {sid for sid, run_id in run_of.items() if run_id in owned}
    replayed = set(
        await session.scalars(
            select(ExperimentScenario.scenario_id).where(ExperimentScenario.experiment_id == experiment.id)
        )
    )
    missing = len(cases - replayed)
    return [f"{missing} cas de régression de l'agent non rejoué(s) par l'expérience"] if missing else []


async def creation_problems(
    session: AsyncSession, config: EvaluationConfig, version_ids: Sequence[uuid.UUID]
) -> list[str]:
    return [*await judge_problems(session, config), *await contamination_problems(session, version_ids)]


async def experiment_problems(session: AsyncSession, experiment: Experiment) -> list[str]:
    """Findings that block (strict) or warn about promoting ``experiment``."""
    config = await session.get(EvaluationConfig, experiment.evaluation_config_id)
    problems = (
        await creation_problems(
            session, config, [experiment.baseline_version_id, experiment.candidate_version_id]
        )
        if config is not None
        else []
    )
    return [*problems, *await regression_case_problems(session, experiment)]
