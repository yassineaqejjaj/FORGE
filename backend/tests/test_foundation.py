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


async def test_concurrent_last_runs_enqueue_finalisation_once(app) -> None:
    """Two sibling runs finishing in parallel transactions must still trigger the finalisation."""
    import asyncio

    from forge.domain.enums import ExecutionStatus, RunOrigin
    from forge.infra.db import get_sessionmaker
    from forge.infra.models import Benchmark, BenchmarkExecution, EvaluationRun
    from forge.services import runs as run_service
    from tests.factories import attach_trace, default_config

    maker = get_sessionmaker()
    async with maker() as session:
        av = await create_agent_version(session)
        sv = await create_scenario_version(session)
        config = await default_config(session)
        bench = Benchmark(slug=f"b-{av.id.hex[:8]}", name="Concurrence", evaluation_config_id=config.id)
        session.add(bench)
        await session.flush()
        execution = BenchmarkExecution(
            benchmark_id=bench.id, number=1, status=ExecutionStatus.running,
            evaluation_config_id=config.id, repetitions=2, total_runs=2,
        )  # fmt: skip
        session.add(execution)
        await session.flush()
        ids = []
        for rep in range(2):
            run = await create_run(
                session,
                sv,
                av,
                origin=RunOrigin.benchmark,
                repetition=rep,
                benchmark_execution_id=execution.id,
            )
            await attach_trace(session, run, output_text="ok")
            ids.append(run.id)
        await session.commit()

    async def finish(run_id) -> None:
        async with maker() as s:
            run = await s.get(EvaluationRun, run_id)
            await run_service.mark_completed(s, run)
            await asyncio.sleep(0.05)  # widen the race window before committing
            await s.commit()

    await asyncio.gather(*(finish(i) for i in ids))
    async with maker() as session:
        jobs = list(
            await session.scalars(
                select(Job).where(
                    Job.kind == JobKind.finalize_execution, Job.dedupe_key.contains(str(execution.id))
                )
            )
        )
        refreshed = await session.get(BenchmarkExecution, execution.id)
    assert len(jobs) == 1
    assert refreshed.completed_runs == 2 and refreshed.status == ExecutionStatus.aggregating
