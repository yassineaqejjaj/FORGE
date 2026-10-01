"""Benchmarks API: CRUD, launch N×M×K, finalisation, results, cancellation, access control."""

from __future__ import annotations

import time
import uuid

from sqlalchemy import func, select

from forge.domain.enums import (
    ExecutionStatus,
    JobKind,
    Role,
    RunOrigin,
    ScenarioVisibility,
)
from forge.infra.db import get_sessionmaker
from forge.infra.models import AuditEvent, EvaluationRun, Job
from forge.infra.queue import PRIORITY_BENCHMARK
from forge.services.run_summaries import load_run_summaries
from tests.analytics_fixtures import complete_runs, make_catalog, scenario_index


async def _create(client, scenario_ids, version_ids, **extra) -> dict:
    body = {
        "name": f"Bench {uuid.uuid4().hex[:6]}",
        "scenarios": [{"scenario_id": str(s)} for s in scenario_ids],
        "agent_version_ids": [str(v) for v in version_ids],
        "repetitions": 2,
        **extra,
    }
    response = await client.post("/api/v1/benchmarks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_benchmark_crud_and_roles(client_as) -> None:
    scenario_ids, versions = await make_catalog()
    viewer = await client_as(Role.viewer)
    editor = await client_as(Role.editor)
    body = {
        "name": "Benchmark PRD",
        "scenarios": [{"scenario_id": str(s)} for s in scenario_ids],
        "agent_version_ids": [str(v) for v in versions],
    }
    assert (await viewer.post("/api/v1/benchmarks", json=body)).status_code == 403
    created = await _create(editor, scenario_ids, versions, name="Benchmark PRD é")
    assert created["slug"].startswith("benchmark-prd-e")
    assert created["n_scenarios"] == 3 and len(created["agents"]) == 2
    assert created["agents"][0]["label"] == "ProductAgent v1.0"
    assert created["evaluation_config_name"]

    by_slug = await viewer.get(f"/api/v1/benchmarks/{created['slug']}")
    assert by_slug.status_code == 200 and by_slug.json()["id"] == created["id"]
    listing = await viewer.get("/api/v1/benchmarks", params={"search": "Benchmark PRD"})
    assert listing.status_code == 200 and any(b["id"] == created["id"] for b in listing.json()["items"])

    patched = await editor.patch(
        f"/api/v1/benchmarks/{created['id']}",
        json={
            "description": "Nouvelle description",
            "repetitions": 3,
            "agent_version_ids": [str(versions[0])],
        },
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["repetitions"] == 3 and len(patched.json()["agents"]) == 1
    duplicate = await editor.post("/api/v1/benchmarks", json={**body, "slug": created["slug"]})
    assert duplicate.status_code == 409
    invalid = await editor.post("/api/v1/benchmarks", json={**body, "agent_version_ids": [str(uuid.uuid4())]})
    assert invalid.status_code == 422 and "introuvable" in invalid.json()["detail"]
    assert (await viewer.get("/api/v1/benchmarks/inconnu")).status_code == 404
    async with get_sessionmaker()() as session:
        actions = set(
            await session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == created["id"]))
        )
    assert {"benchmark.create", "benchmark.update"} <= actions


async def test_launch_finalize_and_results(client_as) -> None:
    scenario_ids, versions = await make_catalog(
        visibilities=[ScenarioVisibility.public, ScenarioVisibility.public, ScenarioVisibility.private]
    )
    editor = await client_as(Role.editor)
    benchmark = await _create(editor, scenario_ids, versions)
    launched = await editor.post(f"/api/v1/benchmarks/{benchmark['id']}/run", json={"trigger": "ci"})
    assert launched.status_code == 202, launched.text
    execution = launched.json()
    assert execution["number"] == 1 and execution["status"] == "running"
    assert execution["total_runs"] == 3 * 2 * 2 and execution["trigger"] == "ci"
    assert len(execution["matrix"]["scenario_version_ids"]) == 3

    async with get_sessionmaker()() as session:
        runs = list(
            await session.scalars(
                select(EvaluationRun)
                .join(Job, Job.run_id == EvaluationRun.id)
                .where(
                    EvaluationRun.benchmark_execution_id == uuid.UUID(execution["id"]),
                    Job.kind == JobKind.execute_run,
                )
                .order_by(Job.created_at)
            )
        )
        priorities = set(
            await session.scalars(
                select(Job.priority).where(
                    Job.run_id.in_([r.id for r in runs]), Job.kind == JobKind.execute_run
                )
            )
        )
    assert len(runs) == 12 and {r.origin for r in runs} == {RunOrigin.benchmark}
    assert priorities == {PRIORITY_BENCHMARK}
    # Interleaved creation: agent versions alternate within each scenario.
    assert [r.agent_version_id for r in runs[:4]] == [versions[0], versions[1], versions[0], versions[1]]

    v2 = versions[1]

    def scorer(run):
        idx = scenario_index(run, scenario_ids)
        base = 70.0 + 5 * idx + run.repetition
        if run.agent_version_id == v2:
            return base + 10, {"dimensions": {"quality": (base + 10) / 100, "safety": 1.0}}
        return base, {"errors": [("HALLUCINATION", "high")] if idx == 0 else []}

    await complete_runs(scorer, benchmark_execution_id=uuid.UUID(execution["id"]))
    detail = await editor.get(f"/api/v1/benchmark-executions/{execution['id']}")
    assert detail.status_code == 200, detail.text
    data = detail.json()
    assert data["status"] == "completed" and data["progress"] == 1.0
    summary = data["summary"]
    assert summary["schema"] == "forge.benchmark-summary/v1"
    assert summary["totals"]["n_scored"] == 12
    assert [r["agent_label"] for r in summary["ranking"]] == ["ProductAgent v1.1", "ProductAgent v1.0"]
    leader = summary["agents"][0]
    assert leader["composite"]["mean"] == 85.5 and leader["composite"]["ci_low"] <= 85.5
    assert summary["agents"][1]["errors_by_type"] == {"HALLUCINATION": 2}
    assert leader["generalisation"]["n_hidden"] == 2 and leader["generalisation"]["gap"] == -7.5
    assert len(summary["matrix"]["cells"]) == 6
    # One benchmark FeedbackReport per agent version (empty while the evaluation module is a stub).
    assert set(summary["feedback_reports"]) in ({str(v) for v in versions}, set())
    assert summary["generated_at"]

    results = await editor.get(
        f"/api/v1/benchmarks/{benchmark['slug']}/results", params={"group_by": "scenario"}
    )
    assert results.status_code == 200, results.text
    rows = results.json()["rows"]
    assert len(rows) == 3 and all(r["composite_ci_low"] is not None for r in rows)
    filtered = await editor.get(
        f"/api/v1/benchmarks/{benchmark['id']}/results",
        params={"group_by": "version", "visibility": "private"},
    )
    assert filtered.json()["n_runs"] == 4
    by_error = await editor.get(
        f"/api/v1/benchmarks/{benchmark['id']}/results", params={"group_by": "error_type"}
    )
    assert by_error.json()["errors"][0]["error_type"] == "HALLUCINATION"
    bad = await editor.get(f"/api/v1/benchmarks/{benchmark['id']}/results", params={"group_by": "nope"})
    assert bad.status_code == 422

    second = await editor.post(f"/api/v1/benchmarks/{benchmark['id']}/run")
    assert second.json()["number"] == 2
    executions = await editor.get(f"/api/v1/benchmarks/{benchmark['id']}/executions")
    assert [e["number"] for e in executions.json()["items"]] == [2, 1]
    # Results default to the latest *completed* execution.
    assert (await editor.get(f"/api/v1/benchmarks/{benchmark['id']}/results")).json()["execution_number"] == 1


async def test_cancel_execution_aggregates_partial_results(client_as) -> None:
    scenario_ids, versions = await make_catalog(n_scenarios=2)
    editor = await client_as(Role.editor)
    benchmark = await _create(editor, scenario_ids, versions, repetitions=1)
    execution = (await editor.post(f"/api/v1/benchmarks/{benchmark['id']}/run")).json()
    async with get_sessionmaker()() as session:
        first = await session.scalar(
            select(EvaluationRun)
            .where(EvaluationRun.benchmark_execution_id == uuid.UUID(execution["id"]))
            .order_by(EvaluationRun.created_at)
            .limit(1)
        )
        assert first is not None
        from tests.factories import complete_with_scores

        await complete_with_scores(session, first, composite=82.0)
        await session.commit()
    viewer = await client_as(Role.viewer)
    assert (await viewer.post(f"/api/v1/benchmark-executions/{execution['id']}/cancel")).status_code == 403
    cancelled = await editor.post(f"/api/v1/benchmark-executions/{execution['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["cancelled_runs"] == 3
    from tests.conftest import run_jobs

    await run_jobs()
    data = (await editor.get(f"/api/v1/benchmark-executions/{execution['id']}")).json()
    assert data["status"] == "cancelled"
    assert data["summary"]["totals"] == {
        **data["summary"]["totals"], "n_runs": 4, "n_scored": 1, "n_cancelled": 3,
    }  # fmt: skip
    again = await editor.post(f"/api/v1/benchmark-executions/{execution['id']}/cancel")
    assert again.status_code == 409


async def test_failed_runs_and_failed_execution(client_as) -> None:
    scenario_ids, versions = await make_catalog(n_scenarios=1, n_agents=1)
    editor = await client_as(Role.editor)
    benchmark = await _create(editor, scenario_ids, versions, repetitions=2)
    execution = (await editor.post(f"/api/v1/benchmarks/{benchmark['id']}/run")).json()
    await complete_runs(lambda run: None, benchmark_execution_id=uuid.UUID(execution["id"]))
    data = (await editor.get(f"/api/v1/benchmark-executions/{execution['id']}")).json()
    assert data["status"] == "failed" and "Aucun run n'a abouti" in data["error"]
    agent = data["summary"]["agents"][0]
    assert agent["n_failed"] == 2 and agent["composite"]["mean"] == 0.0


async def test_clearance_hides_scenarios(client_as) -> None:
    public_ids, versions = await make_catalog(n_scenarios=2, n_agents=1)
    secret_ids, _ = await make_catalog(n_scenarios=1, n_agents=1, classification=3)
    admin = await client_as(Role.admin, clearance=3)
    benchmark = await _create(admin, public_ids + secret_ids, versions, repetitions=1)
    execution = (await admin.post(f"/api/v1/benchmarks/{benchmark['id']}/run")).json()
    await complete_runs(lambda run: (75.0, {}), benchmark_execution_id=uuid.UUID(execution["id"]))

    low = await client_as(Role.editor, clearance=1)
    detail = (await low.get(f"/api/v1/benchmarks/{benchmark['id']}")).json()
    assert detail["hidden_scenarios"] == 1 and len(detail["scenarios"]) == 2
    data = (await low.get(f"/api/v1/benchmark-executions/{execution['id']}")).json()
    assert data["summary"]["restricted"] is True and data["summary"]["totals"]["n_runs"] == 2
    assert len(data["matrix"]["scenario_version_ids"]) == 2
    assert {s["scenario_id"] for s in data["summary"]["matrix"]["scenarios"]} == {str(s) for s in public_ids}
    full = (await admin.get(f"/api/v1/benchmark-executions/{execution['id']}")).json()
    assert full["summary"]["restricted"] is False and full["summary"]["totals"]["n_runs"] == 3
    # A low-clearance editor cannot launch a benchmark containing hidden scenarios.
    refused = await low.post(f"/api/v1/benchmarks/{benchmark['id']}/run")
    assert refused.status_code == 422


async def test_archived_and_limits(client_as) -> None:
    scenario_ids, versions = await make_catalog(n_scenarios=1, n_agents=1)
    editor = await client_as(Role.editor)
    benchmark = await _create(editor, scenario_ids, versions)
    await editor.patch(f"/api/v1/benchmarks/{benchmark['id']}", json={"archived": True})
    refused = await editor.post(f"/api/v1/benchmarks/{benchmark['id']}/run")
    assert refused.status_code == 422 and "archivé" in refused.json()["detail"]
    listing = (await editor.get("/api/v1/benchmarks", params={"archived": True})).json()
    assert any(b["id"] == benchmark["id"] for b in listing["items"])


async def test_load_run_summaries_scales(db_session) -> None:
    """1 200 runs (100 scenarios × 4 agents × 3 repetitions) load and aggregate in seconds."""
    from forge.domain.benchmarks import aggregate_benchmark
    from forge.infra.models import Benchmark, BenchmarkExecution
    from forge.services.benchmarks import resolve_config
    from forge.services.runs import RunPlan, create_runs
    from tests.factories import complete_with_scores, create_agent_version, create_scenario_version

    config = await resolve_config(db_session, None)
    svs = [await create_scenario_version(db_session, name=f"Perf {i}") for i in range(100)]
    first = await create_agent_version(db_session, name="PerfAgent")
    from forge.infra.models import Agent

    agent = await db_session.get(Agent, first.agent_id)
    avs = [first] + [
        await create_agent_version(db_session, agent=agent, version=f"1.{i}", system_prompt=f"p{i}")
        for i in range(1, 4)
    ]
    benchmark = Benchmark(slug=f"perf-{uuid.uuid4().hex[:6]}", name="Perf", evaluation_config_id=config.id)
    db_session.add(benchmark)
    await db_session.flush()
    execution = BenchmarkExecution(
        benchmark_id=benchmark.id, number=1, status=ExecutionStatus.running,
        evaluation_config_id=config.id, repetitions=3,
    )  # fmt: skip
    db_session.add(execution)
    await db_session.flush()
    plans = [
        RunPlan(scenario_version_id=sv.id, agent_version_id=av.id, repetition=rep)
        for rep in range(3)
        for sv in svs
        for av in avs
    ]
    created = await create_runs(
        db_session, plans, evaluation_config=config, origin=RunOrigin.benchmark,
        benchmark_execution_id=execution.id, enqueue=False,
    )  # fmt: skip
    for index, run in enumerate(created):
        await complete_with_scores(
            db_session, run, composite=50.0 + (index % 4) * 10 + (index % 7),
            errors=[("FORMAT_ERROR", "low")] if index % 5 == 0 else None,
        )  # fmt: skip
    await db_session.commit()

    started = time.perf_counter()
    summaries = await load_run_summaries(db_session, benchmark_execution_id=execution.id)
    loaded = time.perf_counter() - started
    summary = aggregate_benchmark(summaries, dimension_weights=config.dimension_weights)
    elapsed = time.perf_counter() - started
    assert len(summaries) == 1200
    assert loaded < 5.0, loaded
    assert elapsed < 10.0, elapsed
    assert summary.totals.n_scored == 1200
    assert sum(len(s.errors) for s in summaries) == 240
    assert all(s.dimensions and s.cost is not None for s in summaries)
    count = await db_session.scalar(
        select(func.count())
        .select_from(EvaluationRun)
        .where(EvaluationRun.benchmark_execution_id == execution.id)
    )
    assert count == 1200
