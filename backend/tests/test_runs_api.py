"""Runs API: ad-hoc creation, list filters / sorting, Run Detail, trace, timeline, manifest, cancel,
retry, clearance."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from forge.domain.enums import JobKind, Role, RunStatus, TraceEventType
from forge.infra.models import Job, Scenario
from tests.factories import (
    attach_trace,
    complete_with_scores,
    create_agent_version,
    create_run,
    create_scenario_version,
)


async def _scored_run(db_session, *, composite: float, latency: float = 3200.0, **scenario_kwargs):
    av = await create_agent_version(db_session, name=f"Agent {uuid.uuid4().hex[:6]}")
    sv = await create_scenario_version(db_session, **scenario_kwargs)
    run = await create_run(db_session, sv, av)
    await attach_trace(
        db_session,
        run,
        output_text="Voici le PRD demandé.",
        latency_ms=latency,
        events=[
            {"type": TraceEventType.llm_call, "name": "gpt", "attributes": {"model": "m", "input_tokens": 10}},
            {"type": TraceEventType.tool_call, "name": "search", "input": {"q": "csv"}, "attributes": {"tool": "search"}},
            {"type": TraceEventType.tool_result, "name": "search", "output": {"hits": 2}, "attributes": {"tool": "search"}},
        ],
    )
    await complete_with_scores(db_session, run, composite=composite, errors=[("FORMAT_ERROR", "low")])
    await db_session.commit()
    return run, av, sv


async def test_create_adhoc_runs(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv1 = await create_scenario_version(db_session)
    sv2 = await create_scenario_version(db_session)
    await db_session.commit()
    editor = await client_as(Role.editor)
    response = await editor.post(
        "/api/v1/runs",
        json={
            "agent_version_id": str(av.id),
            "scenario_ids": [str(sv1.scenario_id)],
            "scenario_version_ids": [str(sv2.id)],
            "repetitions": 2,
            "tags": ["smoke"],
        },
    )
    assert response.status_code == 201, response.text
    runs = response.json()
    assert len(runs) == 4 and {r["status"] for r in runs} == {"pending"}
    assert sorted(r["repetition"] for r in runs) == [0, 0, 1, 1]
    assert all(r["origin"] == "adhoc" and r["tags"] == ["smoke"] for r in runs)
    assert runs[0]["agent_label"] == "Agent de test v1.0" and runs[0]["scenario_name"] == "Scénario de test"
    jobs = list(await db_session.scalars(select(Job).where(Job.run_id == uuid.UUID(runs[0]["id"]))))
    assert [j.kind for j in jobs] == [JobKind.execute_run] and jobs[0].priority == 100

    url = "/api/v1/runs"
    assert (await editor.post(url, json={"agent_version_id": str(av.id)})).status_code == 422
    too_many = await editor.post(url, json={"agent_version_id": str(av.id), "scenario_ids": [str(sv1.scenario_id)], "repetitions": 21})
    assert too_many.status_code == 422
    unknown = await editor.post(url, json={"agent_version_id": str(uuid.uuid4()), "scenario_ids": [str(sv1.scenario_id)]})
    assert unknown.status_code == 404
    viewer = await client_as(Role.viewer)
    assert (await viewer.post(url, json={"agent_version_id": str(av.id), "scenario_ids": [str(sv1.scenario_id)]})).status_code == 403


async def test_list_filters_and_sorting(client_as, db_session) -> None:
    tag = f"t-{uuid.uuid4().hex[:6]}"
    low, av, _ = await _scored_run(db_session, composite=40, latency=9000)
    high, _, _ = await _scored_run(db_session, composite=90, latency=1000)
    for run in (low, high):
        run.tags = [tag]
    await db_session.commit()
    viewer = await client_as(Role.viewer)
    page = (await viewer.get("/api/v1/runs", params={"tag": tag, "sort": "-composite"})).json()
    assert [r["id"] for r in page["items"]] == [str(high.id), str(low.id)] and page["total"] == 2
    assert page["items"][0]["latency_ms"] == 1000 and page["items"][0]["cost"] == 0.012
    by_latency = (await viewer.get("/api/v1/runs", params={"tag": tag, "sort": "-latency"})).json()
    assert by_latency["items"][0]["id"] == str(low.id)
    passed = (await viewer.get("/api/v1/runs", params={"tag": tag, "passed": True})).json()
    assert [r["id"] for r in passed["items"]] == [str(high.id)]
    ranged = (await viewer.get("/api/v1/runs", params={"tag": tag, "min_composite": 50})).json()
    assert ranged["total"] == 1
    by_agent = (await viewer.get("/api/v1/runs", params={"agent_version_id": str(av.id)})).json()
    assert [r["id"] for r in by_agent["items"]] == [str(low.id)]
    by_status = (await viewer.get("/api/v1/runs", params={"tag": tag, "status": ["completed", "failed"]})).json()
    assert by_status["total"] == 2
    by_name = (await viewer.get("/api/v1/runs", params={"tag": tag, "q": av.version and "Agent"})).json()
    assert by_name["total"] == 2
    assert (await viewer.get("/api/v1/runs", params={"sort": "name"})).status_code == 422


async def test_run_detail_trace_timeline_manifest(client_as, db_session) -> None:
    run, av, sv = await _scored_run(db_session, composite=82)
    viewer = await client_as(Role.viewer)
    detail = await viewer.get(f"/api/v1/runs/{run.id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "completed" and body["composite_score"] == 82 and body["redacted"] is False
    assert body["scenario"]["content"]["input"] == {"prompt": sv.input["prompt"]}
    assert body["scenario"]["content"]["canary"] is None
    assert body["agent"]["label"] == "Agent de test v1.0" or body["agent"]["version"] == "1.0"
    assert body["evaluation_config"]["key"] == "forge-default" and body["evaluation_config"]["judges"]
    assert body["trace"]["latency_ms"] == 3200 and body["trace"]["total_tokens"] == 1800
    assert body["trace"]["output_text"] == "Voici le PRD demandé."
    assert body["composite"]["value"] == 82 and body["composite"]["dimensions"]
    assert body["counts"]["errors"] == 1

    trace = (await viewer.get(f"/api/v1/runs/{run.id}/trace")).json()
    assert [e["seq"] for e in trace["events"]] == [1, 2, 3, 4, 5]
    assert trace["tool_calls"][0]["tool"] == "search" and trace["tool_calls"][0]["result"] == {"hits": 2}
    assert trace["model_calls"][0]["model"] == "m"
    assert trace["messages"][-1]["content"] == "Voici le PRD demandé."

    timeline = await viewer.get(f"/api/v1/runs/{run.id}/timeline")
    assert timeline.status_code == 200 and timeline.json()["items"] and timeline.json()["run_id"] == str(run.id)

    manifest = (await viewer.get(f"/api/v1/runs/{run.id}/manifest")).json()
    assert manifest["redacted"] is True and manifest["manifest"]["scenario"]["canary"] is None
    assert "credentials" not in manifest["manifest"]["agent"]
    maintainer = await client_as(Role.maintainer)
    full = (await maintainer.get(f"/api/v1/runs/{run.id}/manifest")).json()
    assert full["redacted"] is False and full["manifest"]["scenario"]["canary"] == sv.canary
    assert (await viewer.get(f"/api/v1/runs/{uuid.uuid4()}")).status_code == 404


async def test_cancel_and_retry(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av, enqueue=True)
    await db_session.commit()
    editor = await client_as(Role.editor)
    early_retry = await editor.post(f"/api/v1/runs/{run.id}/retry")
    assert early_retry.status_code == 409
    cancelled = await editor.post(f"/api/v1/runs/{run.id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await editor.post(f"/api/v1/runs/{run.id}/cancel")).status_code == 409
    retried = await editor.post(f"/api/v1/runs/{run.id}/retry")
    assert retried.status_code == 201, retried.text
    new = retried.json()
    assert new["id"] != str(run.id) and new["status"] == "pending"
    assert new["scenario_version_id"] == str(sv.id) and new["agent_version_id"] == str(av.id)
    assert f"retry-of:{run.id}" in new["tags"]
    await db_session.refresh(run)
    assert run.status == RunStatus.cancelled


async def test_runs_above_clearance_are_hidden(client_as, db_session) -> None:
    run, _, sv = await _scored_run(db_session, composite=70)
    scenario = await db_session.get(Scenario, sv.scenario_id)
    scenario.classification = 3
    tag = f"secret-{uuid.uuid4().hex[:6]}"
    run.tags = [tag]
    await db_session.commit()
    viewer = await client_as(Role.viewer, clearance=1)
    assert (await viewer.get(f"/api/v1/runs/{run.id}")).status_code == 404
    assert (await viewer.get(f"/api/v1/runs/{run.id}/trace")).status_code == 404
    assert (await viewer.get("/api/v1/runs", params={"tag": tag})).json()["total"] == 0
    cleared = await client_as(Role.viewer, clearance=3)
    detail = (await cleared.get(f"/api/v1/runs/{run.id}")).json()
    assert detail["scenario"]["classification_warning"].startswith("Contenu classifié C3")
    editor = await client_as(Role.editor, clearance=1)
    response = await editor.post("/api/v1/runs", json={"agent_version_id": str(run.agent_version_id), "scenario_ids": [str(sv.scenario_id)]})
    assert response.status_code == 404
