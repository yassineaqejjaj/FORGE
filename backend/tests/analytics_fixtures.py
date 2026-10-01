"""Helpers of the analytics integration tests (benchmarks, experiments, calibration, dashboard).

Execution and evaluation belong to other modules: the tests cancel the queued ``execute_run``
jobs and fabricate evaluated runs with :func:`tests.factories.complete_with_scores`, then call
``runs.on_run_terminal`` so that the real finalisation jobs are enqueued and processed.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import pytest_asyncio
from sqlalchemy import select, text, update

from forge.domain.enums import JobKind, JobStatus, RunStatus, ScenarioVisibility
from forge.infra.db import get_sessionmaker
from forge.infra.models import EvaluationRun, Job, Scenario
from forge.services.runs import mark_failed, on_run_terminal
from tests.conftest import run_jobs
from tests.factories import complete_with_scores, create_agent_version, create_scenario_version


@pytest_asyncio.fixture(scope="session")
async def custom_plans(app: object) -> None:
    """WORKAROUND for a foundation bug (reported): ``infra.queue.enqueue_job`` binds the partial
    index predicate of ``ON CONFLICT (dedupe_key) WHERE status IN (…)`` as parameters, so once
    Postgres switches the prepared statement to a generic plan (6th execution on a connection)
    the index can no longer be inferred and the insert fails. Forcing custom plans on the test
    database keeps the analytics tests independent of that fix. Remove once the fix lands.
    """
    from forge.infra.db import dispose_engine, get_engine

    async with get_engine().begin() as conn:
        name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        await conn.execute(text(f'ALTER DATABASE "{name}" SET plan_cache_mode = force_custom_plan'))
    await dispose_engine()  # new pooled connections pick the setting up


#: run → (composite, extra kwargs of complete_with_scores) or None to fail the run.
Scorer = Callable[[EvaluationRun], tuple[float, dict[str, Any]] | None]


async def make_catalog(
    *,
    n_scenarios: int = 3,
    n_agents: int = 2,
    classification: int = 1,
    visibilities: list[ScenarioVisibility] | None = None,
    agent_name: str = "ProductAgent",
) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Create scenarios (latest version 1) and agent versions of ONE agent. Returns ids."""
    async with get_sessionmaker()() as session:
        scenario_ids = []
        for i in range(n_scenarios):
            visibility = (
                (visibilities or [])[i]
                if visibilities and i < len(visibilities)
                else ScenarioVisibility.public
            )
            sv = await create_scenario_version(session, name=f"Scénario {i + 1}", visibility=visibility)
            scenario = await session.get(Scenario, sv.scenario_id)
            assert scenario is not None
            scenario.classification = classification
            scenario_ids.append(sv.scenario_id)
        first = await create_agent_version(session, name=agent_name, version="1.0")
        versions = [first.id]
        from forge.infra.models import Agent

        agent = await session.get(Agent, first.agent_id)
        for i in range(1, n_agents):
            av = await create_agent_version(
                session, agent=agent, version=f"1.{i}", system_prompt=f"Prompt version {i}"
            )
            versions.append(av.id)
        await session.commit()
    return scenario_ids, versions


async def complete_runs(
    scorer: Scorer, *, benchmark_execution_id: uuid.UUID | None = None, experiment_id: uuid.UUID | None = None
) -> int:
    """Cancel queued executions, fabricate evaluated runs, trigger the terminal hooks, run jobs."""
    async with get_sessionmaker()() as session:
        await session.execute(
            update(Job)
            .where(Job.kind == JobKind.execute_run, Job.status == JobStatus.queued)
            .values(status=JobStatus.cancelled)
        )
        conditions = []
        if benchmark_execution_id:
            conditions.append(EvaluationRun.benchmark_execution_id == benchmark_execution_id)
        if experiment_id:
            conditions.append(EvaluationRun.experiment_id == experiment_id)
        runs = list(
            await session.scalars(
                select(EvaluationRun)
                .where(*conditions, EvaluationRun.status == RunStatus.pending)
                .order_by(EvaluationRun.created_at)
            )
        )
        for run in runs:
            outcome = scorer(run)
            if outcome is None:
                await mark_failed(session, run, "Agent injoignable (simulé)")
                continue
            composite, extra = outcome
            await complete_with_scores(session, run, composite=composite, **extra)
            await on_run_terminal(session, run)
        await session.commit()
    return await run_jobs()


def scenario_index(run: EvaluationRun, scenario_ids: list[uuid.UUID]) -> int:
    return scenario_ids.index(run.scenario_id)
