"""Red team: put the attack catalogue into FORGE, run it against an agent version and report how it held up.

The attacks are ordinary scenarios (category ``redteam``) created once and then reused, so everything FORGE
already does with scenarios — runs, traces, evidence, audit — applies. Resistance is read from the
deterministic rules only (``forge.domain.redteam``), never from another model's opinion.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain import redteam
from forge.infra.db import utcnow
from forge.infra.models import AgentVersion, EvaluationRun, Scenario, ScenarioVersion
from forge.services import run_queries, scenarios
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.monitoring import EVALUATED
from forge.services.run_summaries import load_run_summaries
from forge.services.taxonomy import NotFoundError

MAX_RUNS = 2000


async def ensure_pack(
    session: AsyncSession, viewer: Viewer, actor: ActorLike
) -> list[tuple[redteam.Attack, Scenario]]:
    """The scenario of every attack, creating the missing ones (idempotent: one scenario per slug)."""
    pack: list[tuple[redteam.Attack, Scenario]] = []
    for attack in redteam.CATALOG:
        scenario = await scenarios.get_by_slug(session, attack.slug)
        if scenario is None:
            scenario, _ = await scenarios.create_scenario(
                session,
                viewer,
                actor,
                name=f"Red team — {attack.label}",
                category=redteam.CATEGORY,
                content=redteam.scenario_content(attack),
                slug=attack.slug,
                tags=[redteam.TAG, attack.key],
                changelog="Attaque du catalogue red team",
            )
        pack.append((attack, scenario))
    return pack


async def launch(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    agent_version_id: uuid.UUID,
    *,
    repetitions: int = 1,
    created_by: uuid.UUID | None = None,
) -> list[EvaluationRun]:
    """One run per attack and repetition against the agent version, tagged ``redteam``."""
    if await session.get(AgentVersion, agent_version_id) is None:
        raise NotFoundError("Version d'agent introuvable")
    pack = await ensure_pack(session, viewer, actor)
    return await run_queries.create_adhoc_runs(
        session,
        viewer,
        actor,
        run_queries.RunRequest(
            agent_version_id=agent_version_id,
            scenario_ids=[scenario.id for _, scenario in pack],
            repetitions=repetitions,
            tags=[redteam.TAG],
        ),
        created_by=created_by,
    )


async def report(
    session: AsyncSession, viewer: Viewer, agent_version_id: uuid.UUID, *, days: int = 30
) -> dict[str, Any]:
    if await session.get(AgentVersion, agent_version_id) is None:
        raise NotFoundError("Version d'agent introuvable")
    since = utcnow() - timedelta(days=days)
    ids = list(
        await session.scalars(
            select(EvaluationRun.id)
            .join(ScenarioVersion, ScenarioVersion.id == EvaluationRun.scenario_version_id)
            .join(Scenario, Scenario.id == ScenarioVersion.scenario_id)
            .where(
                EvaluationRun.agent_version_id == agent_version_id,
                EvaluationRun.created_at >= since,
                EvaluationRun.status.in_(list(EVALUATED)),
                Scenario.category == redteam.CATEGORY,
            )
            .order_by(EvaluationRun.created_at.desc())
            .limit(MAX_RUNS)
        )
    )
    summaries = await load_run_summaries(session, run_ids=ids, viewer=viewer) if ids else []
    families, overall = redteam.report(summaries)
    return {
        "agent_version_id": str(agent_version_id),
        "days": days,
        "resistance": overall,
        "status": _status(families),
        "families": [
            {
                "key": f.key,
                "label": f.label,
                "summary": f.summary,
                "runs": f.runs,
                "resisted": f.resisted,
                "resistance": f.resistance,
                "status": f.status,
                "failed_run_ids": f.failed_run_ids,
                "error_types": f.error_types,
            }
            for f in families
        ],
    }


def _status(families: list[redteam.FamilyResult]) -> str:
    """``not_run`` before any attack was evaluated, ``vulnerable`` if a family is weak, else solid/fragile."""
    evaluated = [f for f in families if f.runs]
    if not evaluated:
        return "not_run"
    if any(f.status == "weak" for f in evaluated):
        return "vulnerable"
    return "solid" if all(f.status == "solid" for f in evaluated) else "fragile"
