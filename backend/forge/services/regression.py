"""Failed run → regression scenario.

A run that failed in production (or in a test) is turned into a *variant* of its scenario: same rules,
criteria and expected behaviour, but with the input and context the run actually received, and the errors it
raised written down as constraints. The variant joins the scenario family, so experiments can replay the
case and a fix is only kept if it passes it. Idempotent: promoting the same run twice returns the same
scenario.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import RunStatus
from forge.infra.models import ExecutionTrace, RunError, ScenarioVersion
from forge.services import audit
from forge.services import scenarios as scenario_service
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.run_queries import get_visible_run
from forge.services.taxonomy import ConflictError, InvalidError

MAX_ERRORS = 5
MAX_TAGS = 50


@dataclass(slots=True)
class Promotion:
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    slug: str
    created: bool


async def promote_run(
    session: AsyncSession, viewer: Viewer, actor: ActorLike, run_id: uuid.UUID, *, label: str | None = None
) -> Promotion:
    run, _ = await get_visible_run(session, viewer, run_id)
    errors = list(
        await session.scalars(
            select(RunError.description).where(RunError.run_id == run.id).order_by(RunError.created_at)
        )
    )
    if run.status != RunStatus.failed and run.passed is not False and not errors:
        raise InvalidError("Seuls les runs en échec ou non réussis peuvent devenir des cas de régression")
    trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id))
    if trace is None or not isinstance(trace.input, dict) or not trace.input:
        raise InvalidError("Ce run n'a pas d'entrée enregistrée : impossible d'en faire un scénario")

    version = await session.get(ScenarioVersion, run.scenario_version_id)
    parent = await scenario_service.get_version(session, viewer, run.scenario_version_id)
    scenario = parent[0]
    assert version is not None
    context = trace.input.get("context")
    seen = list(dict.fromkeys(" ".join(e.split())[:300] for e in errors if e))[:MAX_ERRORS]
    constraints = list(version.constraints or [])
    if seen:
        constraints.append("Régression — ne pas reproduire : " + " ; ".join(seen))
    overrides: dict[str, Any] = {
        "input": {k: v for k, v in trace.input.items() if k != "context"},
        "constraints": constraints,
    }
    if isinstance(context, dict):
        overrides["context"] = context
    slug_label = label or f"regression-{run.id.hex[:8]}"
    tags = list(dict.fromkeys([*(scenario.tags or []), "regression", f"from-run:{run.id}"]))[:MAX_TAGS]
    try:
        variant, variant_version = await scenario_service.create_variant(
            session,
            viewer,
            actor,
            scenario,
            label=slug_label,
            overrides=overrides,
            name=f"{scenario.name} — régression {run.id.hex[:8]}",
            tags=tags,
            changelog=f"Cas de régression issu du run {run.id}",
        )
    except ConflictError:
        existing = await scenario_service.get_by_slug(
            session, f"{scenario.slug}_variant_{scenario_service.slug_part(slug_label)}"
        )
        if existing is None:
            raise
        latest = await scenario_service.latest_version(session, existing)
        assert latest is not None
        return Promotion(existing.id, latest.id, existing.slug, created=False)
    await audit.record(
        session,
        actor,
        "run.promote",
        "scenario",
        variant.id,
        summary=f"Run {run.id} promu en scénario de régression {variant.slug}",
        details={"run_id": run.id, "scenario_id": variant.id, "errors": len(seen)},
    )
    return Promotion(variant.id, variant_version.id, variant.slug, created=True)
