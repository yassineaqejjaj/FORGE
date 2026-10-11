"""Context-gap loop: a run failed for lack of information → ORBIT fills it → re-test on the new snapshot.

1. **Diagnose**: the information a run was missing comes from its ``MISSING_INFORMATION`` errors (or from
   the caller, who knows better). The ORBIT request that served the run's context is found on the trace
   (FORGE-executed runs) or in the run manifest reported by the producer (NOVA).
2. **Fill**: ``POST …/context/requests/{id}/complete`` makes ORBIT re-assemble that context around the gaps
   and save it as the next version of the snapshot. Nothing is overwritten.
3. **Re-test** (optional): a candidate agent version pinned to the new snapshot is created from the run's
   version, and the same scenario version is run against it, so the effect is measured, not assumed.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import BuiltinErrorType, RunOrigin
from forge.infra.models import Agent, AgentVersion, EvaluationRun, ExecutionTrace, RunError
from forge.services import agents as agent_service
from forge.services import audit, run_links, runs
from forge.services.access import Viewer
from forge.services.audit import ActorLike
from forge.services.context_providers import ContextPreparationError, call_orbit, orbit_config_for
from forge.services.mapping import specs_from_manifest
from forge.services.run_queries import get_visible_run, resolve_config
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

MAX_GAPS = 10
MAX_GAP_CHARS = 300


@dataclass(slots=True)
class GapRequest:
    missing: list[str] = field(default_factory=list)  # empty: taken from the run's MISSING_INFORMATION errors
    orbit_project: str | None = None  # when neither the agent's config nor the run says which project
    credential_id: uuid.UUID | None = None
    snapshot: str | None = None  # where ORBIT saves the result (default: next version of the served snapshot)
    retest: bool = False


@dataclass(slots=True)
class GapResult:
    run_id: uuid.UUID
    missing: list[str]
    orbit_request_id: str
    orbit_project: str
    completion: dict[str, Any]
    candidate_version_id: uuid.UUID | None = None
    retest_run_id: uuid.UUID | None = None


async def missing_from_errors(session: AsyncSession, run_id: uuid.UUID) -> list[str]:
    rows = await session.scalars(
        select(RunError.description)
        .where(RunError.run_id == run_id, RunError.error_type == BuiltinErrorType.MISSING_INFORMATION.value)
        .order_by(RunError.created_at)
    )
    cleaned = [" ".join(d.split())[:MAX_GAP_CHARS] for d in rows if d and len(d.split()) >= 1]
    return [d for d in dict.fromkeys(cleaned) if len(d) >= 3][:MAX_GAPS]


async def served_context_of(session: AsyncSession, run: EvaluationRun) -> tuple[str | None, str | None]:
    """``(orbit_request_id, orbit_project)`` recorded for the run's context, whichever way it was produced."""
    reported = (run.source_manifest or {}).get("context") or {}
    request_id, project = reported.get("retrieval_id"), reported.get("project_slug")
    if not request_id:
        trace_context = (
            await session.scalar(select(ExecutionTrace.metadata_).where(ExecutionTrace.run_id == run.id))
            or {}
        ).get("context") or {}
        request_id = trace_context.get("orbit_request_id")
        project = project or trace_context.get("orbit_project")
    return (str(request_id) if request_id else None, str(project) if project else None)


async def fill_context_gap(
    session: AsyncSession,
    viewer: Viewer,
    actor: ActorLike,
    run_id: uuid.UUID,
    request: GapRequest,
    *,
    created_by: uuid.UUID | None,
) -> GapResult:
    run, _ = await get_visible_run(session, viewer, run_id)
    missing = [m.strip()[:MAX_GAP_CHARS] for m in request.missing if m and len(m.strip()) >= 3][:MAX_GAPS]
    missing = missing or await missing_from_errors(session, run.id)
    if not missing:
        raise InvalidError("Aucune information manquante : précisez `missing` ou évaluez le run d'abord")
    request_id, project = await served_context_of(session, run)
    if not request_id:
        raise InvalidError("Ce run n'a pas de requête ORBIT à compléter (aucun contexte ORBIT enregistré)")
    agent_config = dict(specs_from_manifest(run.manifest).agent.context_config or {})
    orbit_cfg = dict(agent_config.get("orbit") or {})
    orbit_cfg["project"] = orbit_cfg.get("project") or request.orbit_project or project
    if request.credential_id:
        orbit_cfg["credential_id"] = str(request.credential_id)
    if not orbit_cfg["project"]:
        raise InvalidError("Projet ORBIT inconnu : précisez `orbit_project`")
    try:
        orbit = await orbit_config_for(session, {**agent_config, "orbit": orbit_cfg})
        payload: dict[str, Any] = {"missing": missing}
        if request.snapshot:
            payload["snapshot"] = {"name": request.snapshot}
        completion = await call_orbit(
            orbit,
            "POST",
            f"/api/v1/projects/{quote(orbit.project, safe='')}"
            f"/context/requests/{quote(request_id, safe='')}/complete",
            run_id=str(run.id),
            payload=payload,
        )
    except ContextPreparationError as exc:
        raise ConflictError(str(exc)) from exc

    result = GapResult(
        run_id=run.id,
        missing=missing,
        orbit_request_id=request_id,
        orbit_project=orbit.project,
        completion=completion,
    )
    snapshot = completion.get("snapshot") if isinstance(completion.get("snapshot"), dict) else None
    if request.retest and snapshot:
        await _retest(session, actor, run, result, orbit_cfg, snapshot, created_by=created_by)
    await audit.record(
        session,
        actor,
        "run.context_gap",
        "evaluation_run",
        run.id,
        summary=f"Manque de contexte comblé via ORBIT ({len(missing)} point(s))",
        details={
            "orbit_request_id": request_id,
            "new_request_id": completion.get("request_id"),
            "snapshot": snapshot,
            "retest_run_id": result.retest_run_id,
        },
    )
    return result


async def _retest(
    session: AsyncSession,
    actor: ActorLike,
    run: EvaluationRun,
    result: GapResult,
    orbit_cfg: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    created_by: uuid.UUID | None,
) -> None:
    base = await session.get(AgentVersion, run.agent_version_id)
    agent = await session.get(Agent, run.agent_id)
    if base is None or agent is None:
        raise NotFoundError("Version d'agent introuvable")
    name, version = str(snapshot.get("name")), snapshot.get("version")
    context_config = {
        "source": "orbit_snapshot",
        "orbit": {**orbit_cfg, "snapshot": name, "version": str(version or "latest")},
    }
    candidate = await agent_service.create_version(
        session,
        actor,
        agent,
        {
            "base_version_id": base.id,
            "context_config": context_config,
            "changelog": f"Contexte complété par ORBIT : {name}@v{version} (manque du run {run.id})",
        },
        created_by=created_by,
    )
    config = await resolve_config(session, run.evaluation_config_id)
    (retest,) = await runs.create_runs(
        session,
        [runs.RunPlan(scenario_version_id=run.scenario_version_id, agent_version_id=candidate.id)],
        evaluation_config=config,
        origin=RunOrigin.adhoc,
        created_by=created_by,
        tags=["context-gap", f"context-gap-of:{run.id}"],
    )
    run_links.apply_links(
        retest,
        context_snapshot_id=f"{name}@v{version}",
        release_id=None,
        manifest={"context": {"snapshot_id": f"{name}@v{version}"}, "context_gap_of": str(run.id)},
    )
    result.candidate_version_id, result.retest_run_id = candidate.id, retest.id
