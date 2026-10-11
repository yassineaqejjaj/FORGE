"""Experiments API: creation & pinning, interleaved launch, comparison, recommendation, gate, cancel."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from forge.domain.enums import ExperimentArm, JobKind, Role, RunOrigin
from forge.infra.db import get_sessionmaker
from forge.infra.models import AuditEvent, EvaluationRun, ExperimentScenario, Job
from forge.infra.queue import PRIORITY_EXPERIMENT
from tests.analytics_fixtures import complete_runs, make_catalog, scenario_index


async def _experiment(client, baseline, candidate, scenario_ids, **extra) -> dict:
    response = await client.post(
        "/api/v1/experiments",
        json={
            "baseline_version_id": str(baseline),
            "candidate_version_id": str(candidate),
            **({"scenario_ids": [str(s) for s in scenario_ids]} if scenario_ids else {}),
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_validation(client_as) -> None:
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=2)
    editor = await client_as(Role.editor)
    viewer = await client_as(Role.viewer)
    body = {
        "baseline_version_id": str(v1),
        "candidate_version_id": str(v2),
        "scenario_ids": [str(scenario_ids[0])],
    }
    assert (await viewer.post("/api/v1/experiments", json=body)).status_code == 403
    same = await editor.post("/api/v1/experiments", json={**body, "candidate_version_id": str(v1)})
    assert same.status_code == 422 and "différentes" in same.json()["detail"]
    missing = await editor.post(
        "/api/v1/experiments", json={**body, "candidate_version_id": str(uuid.uuid4())}
    )
    assert missing.status_code == 422
    no_scenario = await editor.post(
        "/api/v1/experiments", json={"baseline_version_id": str(v1), "candidate_version_id": str(v2)}
    )
    assert no_scenario.status_code == 422
    unknown = await editor.post(
        "/api/v1/experiments", json={**body, "benchmark_id": "inconnu", "scenario_ids": None}
    )
    assert unknown.status_code == 404


async def test_experiment_from_benchmark_ship(client_as) -> None:
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=8)
    editor = await client_as(Role.editor)
    bench = await editor.post(
        "/api/v1/benchmarks",
        json={
            "name": "Bench expérience",
            "scenarios": [{"scenario_id": str(s)} for s in scenario_ids],
            "agent_version_ids": [str(v1)],
            "repetitions": 2,
        },
    )
    assert bench.status_code == 201, bench.text
    created = await _experiment(
        editor,
        v1,
        v2,
        [],
        benchmark_id=bench.json()["slug"],
        hypothesis="Le nouveau prompt aide",
    )
    assert created["status"] == "running" and created["repetitions"] == 2
    assert created["total_runs"] == 8 * 2 * 2 and created["n_scenarios"] == 8
    assert created["baseline"]["label"] == "ProductAgent v1.0" and created["warnings"] == []
    experiment_id = uuid.UUID(created["id"])

    async with get_sessionmaker()() as session:
        runs = list(
            await session.scalars(
                # Execution jobs are enqueued one by one in plan order (runs share one flush timestamp).
                select(EvaluationRun)
                .join(Job, Job.run_id == EvaluationRun.id)
                .where(EvaluationRun.experiment_id == experiment_id, Job.kind == JobKind.execute_run)
                .order_by(Job.created_at)
            )
        )
        pinned = list(
            await session.scalars(
                select(ExperimentScenario).where(ExperimentScenario.experiment_id == experiment_id)
            )
        )
        priorities = set(
            await session.scalars(
                select(Job.priority).where(
                    Job.run_id.in_([r.id for r in runs]), Job.kind == JobKind.execute_run
                )
            )
        )
    assert len(pinned) == 8 and priorities == {PRIORITY_EXPERIMENT}
    assert {r.origin for r in runs} == {RunOrigin.experiment}
    # Interleaved: each consecutive pair covers both arms of the same scenario, the first arm alternates.
    assert [r.arm for r in runs[:4]] == [
        ExperimentArm.baseline, ExperimentArm.candidate, ExperimentArm.candidate, ExperimentArm.baseline,
    ]  # fmt: skip
    assert runs[0].scenario_id == runs[1].scenario_id

    def scorer(run):
        idx = scenario_index(run, scenario_ids)
        base = 60.0 + 3 * idx + run.repetition
        if run.arm == ExperimentArm.candidate:
            value = base + 8 + (idx % 3)
            return value, {"dimensions": {"quality": value / 100, "safety": 1.0}}
        return base, {"dimensions": {"quality": base / 100, "safety": 1.0}}

    provisional = await editor.get(f"/api/v1/experiments/{experiment_id}/comparison")
    assert provisional.status_code == 200 and provisional.json()["provisional"] is True
    pending_gate = (await editor.get(f"/api/v1/experiments/{experiment_id}/gate")).json()
    assert pending_gate["passed"] is False and "pas terminée" in pending_gate["reasons"][0]

    await complete_runs(scorer, experiment_id=experiment_id)
    detail = (await editor.get(f"/api/v1/experiments/{experiment_id}")).json()
    assert detail["status"] == "completed" and detail["recommendation"] == "ship"
    assert detail["summary"].startswith("Déploiement recommandé")
    comparison = (await editor.get(f"/api/v1/experiments/{experiment_id}/comparison")).json()
    assert comparison["schema"] == "forge.experiment-comparison/v1" and comparison["provisional"] is False
    assert comparison["n_pairs"] == 8
    assert comparison["composite"]["verdict"] == "better"
    assert comparison["composite"]["delta"] == pytest.approx(8 + 7 / 8)  # 8 + mean(idx % 3)
    assert comparison["composite"]["ci_low"] > 0 and comparison["composite"]["p_value"] < 0.05
    assert {d["key"] for d in comparison["dimensions"]} == {"quality", "safety"}
    assert comparison["regressions"] == []
    assert comparison["noise"]["repetitions"] == 2
    gate = (await editor.get(f"/api/v1/experiments/{experiment_id}/gate")).json()
    assert gate["passed"] is True and gate["recommendation"] == "ship"
    strict = (await editor.get(f"/api/v1/experiments/{experiment_id}/gate", params={"strict": True})).json()
    assert strict["passed"] is True
    listing = (await editor.get("/api/v1/experiments", params={"agent_version_id": str(v2)})).json()
    assert any(e["id"] == str(experiment_id) and e["recommendation"] == "ship" for e in listing["items"])
    by_reco = (await editor.get("/api/v1/experiments", params={"recommendation": "do_not_ship"})).json()
    assert all(e["id"] != str(experiment_id) for e in by_reco["items"])
    async with get_sessionmaker()() as session:
        actions = set(
            await session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == str(experiment_id)))
        )
    assert {"experiment.create", "experiment.finalize"} <= actions


async def test_regression_blocks_the_gate(client_as) -> None:
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=8)
    editor = await client_as(Role.editor)
    created = await _experiment(editor, v1, v2, scenario_ids, repetitions=1, name="Régression")
    regressed = scenario_ids[2]

    def scorer(run):
        idx = scenario_index(run, scenario_ids)
        base = 70.0 + idx
        if run.arm == ExperimentArm.candidate:
            if run.scenario_id == regressed:
                return 0.0, {"gate_failed": True, "errors": [("DATA_LEAK", "critical")]}
            return base + 2, {}
        return base, {}

    await complete_runs(scorer, experiment_id=uuid.UUID(created["id"]))
    comparison = (await editor.get(f"/api/v1/experiments/{created['id']}/comparison")).json()
    assert comparison["recommendation"]["recommendation"] == "do_not_ship"
    (regression,) = comparison["regressions"]
    assert regression["scenario_id"] == str(regressed) and regression["severity"] == "critical"
    assert regression["new_critical_errors"] == ["DATA_LEAK"]
    assert comparison["errors"]["appeared"] == ["DATA_LEAK"]
    gate = (await editor.get(f"/api/v1/experiments/{created['id']}/gate")).json()
    assert gate["passed"] is False and gate["regressions"] == 1
    assert any("Régression critique" in r for r in gate["reasons"])


async def test_same_hash_warning_and_cancel(client_as) -> None:
    scenario_ids, (v1,) = await make_catalog(n_scenarios=2, n_agents=1)
    async with get_sessionmaker()() as session:
        from forge.infra.models import Agent, AgentVersion
        from tests.factories import create_agent_version

        first = await session.get(AgentVersion, v1)
        agent = await session.get(Agent, first.agent_id)
        twin = await create_agent_version(session, agent=agent, version="1.0-bis")  # same behaviour
        await session.commit()
    editor = await client_as(Role.editor)
    created = await _experiment(editor, v1, twin.id, scenario_ids)
    assert any("même hash" in w for w in created["warnings"])
    cancelled = await editor.post(f"/api/v1/experiments/{created['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    from tests.conftest import run_jobs

    await run_jobs()
    detail = (await editor.get(f"/api/v1/experiments/{created['id']}")).json()
    assert detail["status"] == "cancelled" and detail["recommendation"] == "inconclusive"
    gate = (await editor.get(f"/api/v1/experiments/{created['id']}/gate")).json()
    assert gate["passed"] is False and "annulée" in gate["reasons"][0]
    assert (await editor.post(f"/api/v1/experiments/{created['id']}/cancel")).status_code == 409


async def test_hidden_scenarios_are_excluded_for_low_clearance(client_as) -> None:
    public_ids, (v1, v2) = await make_catalog(n_scenarios=6)
    secret_ids, _ = await make_catalog(n_scenarios=1, n_agents=1, classification=3)
    admin = await client_as(Role.admin, clearance=3)
    created = await _experiment(admin, v1, v2, public_ids + secret_ids)
    secret = secret_ids[0]

    def scorer(run):
        if run.scenario_id == secret:
            return (10.0 if run.arm == ExperimentArm.candidate else 75.0), {}
        base = 70.0 + public_ids.index(run.scenario_id)
        return (base + 10 if run.arm == ExperimentArm.candidate else base), {}

    await complete_runs(scorer, experiment_id=uuid.UUID(created["id"]))
    full = (await admin.get(f"/api/v1/experiments/{created['id']}/comparison")).json()
    assert any(r["scenario_id"] == str(secret) for r in full["regressions"])
    low = await client_as(Role.viewer, clearance=1)
    detail = (await low.get(f"/api/v1/experiments/{created['id']}")).json()
    assert detail["hidden_scenarios"] == 1 and len(detail["scenarios"]) == 6
    restricted = (await low.get(f"/api/v1/experiments/{created['id']}/comparison")).json()
    assert restricted["restricted"] is True and restricted["n_pairs"] == 6
    assert all(s["scenario_id"] != str(secret) for s in restricted["scenarios"])
    assert str(secret) not in str(restricted)
    gate = (await low.get(f"/api/v1/experiments/{created['id']}/gate")).json()
    assert "habilitation" in gate["reasons"][-1]


# --- Several candidates against one baseline ---------------------------------------------------------


async def _multi(client, baseline, candidates, scenario_ids, **extra):
    return await client.post(
        "/api/v1/experiments/multi",
        json={
            "baseline_version_id": str(baseline),
            "candidate_version_ids": [str(c) for c in candidates],
            "scenario_ids": [str(s) for s in scenario_ids],
            "repetitions": 1,
            **extra,
        },
    )


async def test_multi_experiment_validation_and_atomicity(client_as) -> None:
    scenario_ids, (v1, v2, v3) = await make_catalog(n_scenarios=3, n_agents=3)
    editor = await client_as(Role.editor)
    viewer = await client_as(Role.viewer)
    assert (await _multi(viewer, v1, [v2, v3], scenario_ids)).status_code == 403
    assert (await _multi(editor, v1, [v2], scenario_ids)).status_code == 422  # at least two candidates
    assert (await _multi(editor, v1, [v2, v2], scenario_ids)).status_code == 422  # duplicates collapse to one
    too_many = [uuid.uuid4() for _ in range(6)]
    assert (await _multi(editor, v1, too_many, scenario_ids)).status_code == 422
    before = len((await editor.get("/api/v1/experiments")).json()["items"])
    bad = await _multi(editor, v1, [v2, uuid.uuid4()], scenario_ids)
    assert bad.status_code == 422  # one unknown candidate cancels the whole group
    assert len((await editor.get("/api/v1/experiments")).json()["items"]) == before
    unknown = await editor.get(f"/api/v1/experiments/multi/{uuid.uuid4()}")
    assert unknown.status_code == 404


async def test_multi_experiment_picks_a_winner_only_after_correction(client_as) -> None:
    scenario_ids, (base, good, flat, worse) = await make_catalog(n_scenarios=8, n_agents=4)
    editor = await client_as(Role.editor)
    created = await _multi(editor, base, [good, flat, worse], scenario_ids, name="Trois variantes")
    assert created.status_code == 201, created.text
    body = created.json()
    group_id, experiments = body["group_id"], body["experiments"]
    assert len(experiments) == 3 and all(e["status"] == "running" for e in experiments)

    pending = (await editor.get(f"/api/v1/experiments/multi/{group_id}")).json()
    assert pending["complete"] is False and pending["winner"] is None and "pas terminées" in pending["reason"]

    gain = {good: 9.0, flat: 0.0, worse: -6.0}

    def scorer(run):
        idx = scenario_index(run, scenario_ids)
        value = 60.0 + 3 * idx
        if run.arm == ExperimentArm.candidate:
            # "flat" only wobbles around zero (+0.5 / -0.5): no real effect.
            wobble = (0.5 if idx % 2 else -0.5) if run.agent_version_id == flat else 0.0
            value += gain[run.agent_version_id] + wobble + (idx % 2) * 0.1
        return value, {"dimensions": {"quality": value / 100, "safety": 1.0}}

    for experiment in experiments:
        await complete_runs(scorer, experiment_id=uuid.UUID(experiment["id"]))

    report = (await editor.get(f"/api/v1/experiments/multi/{group_id}")).json()
    assert report["complete"] is True and report["correction"] == "holm_bonferroni"
    by_candidate = {c["candidate_version_id"]: c for c in report["candidates"]}
    best, neutral, bad = by_candidate[str(good)], by_candidate[str(flat)], by_candidate[str(worse)]
    assert best["delta"] > 8 and best["significant"] is True and best["eligible"] is True
    assert best["p_adjusted"] >= best["p_value"]  # correction never lowers a p-value
    assert neutral["significant"] is False and neutral["eligible"] is False
    assert bad["delta"] < 0 and bad["significant"] is False and bad["eligible"] is False
    assert report["winner"]["candidate_version_id"] == str(good)
    assert report["candidates"][0]["candidate_version_id"] == str(good)  # ranked first
    assert "p corrigée" in report["reason"]
    # Each pairwise experiment keeps its own gate: the group does not replace it.
    gate = (await editor.get(f"/api/v1/experiments/{experiments[2]['id']}/gate")).json()
    assert gate["passed"] is False


async def test_multi_experiment_without_a_real_gain_keeps_the_baseline(client_as) -> None:
    scenario_ids, (base, a, b) = await make_catalog(n_scenarios=8, n_agents=3)
    editor = await client_as(Role.editor)
    created = (await _multi(editor, base, [a, b], scenario_ids)).json()

    def scorer(run):
        idx = scenario_index(run, scenario_ids)
        wobble = (0.4 if idx % 2 else -0.4) if run.arm == ExperimentArm.candidate else 0.0
        value = 60.0 + 3 * idx + wobble
        return value, {"dimensions": {"quality": value / 100, "safety": 1.0}}

    for experiment in created["experiments"]:
        await complete_runs(scorer, experiment_id=uuid.UUID(experiment["id"]))
    report = (await editor.get(f"/api/v1/experiments/multi/{created['group_id']}")).json()
    assert report["complete"] is True and report["winner"] is None
    assert not any(c["eligible"] for c in report["candidates"])
    assert "on conserve la baseline" in report["reason"] or "aucun n'est livrable" in report["reason"]
