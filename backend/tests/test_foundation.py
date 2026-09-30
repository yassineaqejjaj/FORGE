"""Foundation: run creation freezes a manifest, jobs are enqueued, terminal hooks update parents."""

from __future__ import annotations

from sqlalchemy import select

from forge.domain.enums import JobKind, JobStatus, RunStatus
from forge.infra.models import Job
from forge.services.mapping import specs_from_manifest
from tests.factories import create_agent_version, create_run, create_scenario_version


async def test_create_run_freezes_manifest_and_enqueues(db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(
        db_session, rules=[{"type": "contains", "params": {"keywords": ["PRD"]}}]
    )
    run = await create_run(db_session, sv, av, enqueue=True)
    await db_session.commit()

    assert run.status == RunStatus.pending
    assert run.manifest["schema"] == "forge.run-manifest/v1"
    assert "credentials" not in run.manifest["agent"]
    specs = specs_from_manifest(run.manifest)
    assert specs.scenario.scenario_version_id == str(sv.id)
    assert specs.scenario.rules[0].type == "contains"
    assert specs.agent.agent_version_id == str(av.id)
    assert specs.config.dimension_weights["quality"] > 0
    assert specs.config.judges, "default configuration must pin at least one judge"
    jobs = list(await db_session.scalars(select(Job).where(Job.run_id == run.id)))
    assert [(j.kind, j.status) for j in jobs] == [(JobKind.execute_run, JobStatus.queued)]


async def test_repetitions_share_manifest_hash(db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    first = await create_run(db_session, sv, av, repetition=0)
    second = await create_run(db_session, sv, av, repetition=1)
    assert first.manifest_hash == second.manifest_hash
    assert first.otel_trace_id != second.otel_trace_id
