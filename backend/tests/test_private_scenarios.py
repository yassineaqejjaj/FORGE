"""Private evaluation (§3.3) and classification (§3.4) across the platform endpoints."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role, ScenarioVisibility, TraceEventType
from forge.infra.models import Scenario
from tests.factories import (
    attach_trace,
    complete_with_scores,
    create_agent_version,
    create_run,
    create_scenario_version,
)

PRIVATE_CONTENT = {
    "input": {"prompt": "Question secrète du benchmark"},
    "expected_output": "Réponse attendue secrète",
    "constraints": ["Contrainte secrète"],
    "rules": [{"type": "contains", "params": {"keywords": ["secret"]}}],
}


async def test_only_maintainers_create_or_edit_private_scenarios(client_as) -> None:
    editor = await client_as(Role.editor)
    body = {"name": "Privé", "category": "compliance", "visibility": "private", "content": PRIVATE_CONTENT}
    assert (await editor.post("/api/v1/scenarios", json=body)).status_code == 403
    maintainer = await client_as(Role.maintainer)
    created = await maintainer.post("/api/v1/scenarios", json=body)
    assert created.status_code == 201, created.text
    scenario = created.json()
    assert scenario["latest"]["input"] == PRIVATE_CONTENT["input"] and scenario["latest"]["canary"]

    sid = scenario["id"]
    assert (await editor.post(f"/api/v1/scenarios/{sid}/versions", json={"content": {"constraints": []}})).status_code == 403
    assert (await editor.post(f"/api/v1/scenarios/{sid}/variants", json={"label": "x"})).status_code == 403
    assert (await editor.patch(f"/api/v1/scenarios/{sid}", json={"visibility": "public"})).status_code == 403
    renamed = await editor.patch(f"/api/v1/scenarios/{sid}", json={"name": "Privé renommé"})
    assert renamed.status_code == 200  # metadata stays editable

    public = (await editor.post("/api/v1/scenarios", json={**body, "visibility": "public"})).json()
    assert (await editor.patch(f"/api/v1/scenarios/{public['id']}", json={"visibility": "private"})).status_code == 403
    assert (await maintainer.patch(f"/api/v1/scenarios/{public['id']}", json={"visibility": "private"})).status_code == 200


async def test_private_content_is_redacted_for_non_maintainers(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    tag = f"priv-{uuid.uuid4().hex[:6]}"
    scenario = (
        await maintainer.post(
            "/api/v1/scenarios",
            json={"name": "Privé", "category": "compliance", "visibility": "private", "tags": [tag], "content": PRIVATE_CONTENT},
        )
    ).json()
    for role in (Role.viewer, Role.editor):
        c = await client_as(role)
        listing = (await c.get("/api/v1/scenarios", params={"tag": tag})).json()
        assert listing["total"] == 1 and listing["items"][0]["name"] == "Privé"
        detail = (await c.get(f"/api/v1/scenarios/{scenario['id']}")).json()
        latest = detail["latest"]
        assert latest["redacted"] is True
        for field in ("input", "expected_output", "constraints", "context", "tool_mocks", "canary"):
            assert latest[field] is None, field
        assert latest["rules"][0]["params"] == {} and latest["rules"][0]["type"] == "contains"
        versions = (await c.get(f"/api/v1/scenarios/{scenario['id']}/versions")).json()
        assert all(v["input"] is None for v in versions)
        assert "secrète" not in str(detail)
        exported = await c.get("/api/v1/scenarios/export", params={"tag": tag})
        assert exported.headers["X-Forge-Skipped-Private"] == "1" and "secrète" not in exported.text


async def test_private_runs_show_results_but_not_content(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(
        db_session, visibility=ScenarioVisibility.private, prompt="Prompt confidentiel", expected_output="Attendu confidentiel"
    )
    run = await create_run(db_session, sv, av)
    await attach_trace(
        db_session,
        run,
        output_text="Sortie confidentielle",
        events=[{"type": TraceEventType.tool_call, "name": "search", "input": {"q": "confidentiel"}, "attributes": {"tool": "search", "arguments": {"q": "x"}}}],
    )
    await complete_with_scores(db_session, run, composite=64)
    await db_session.commit()

    viewer = await client_as(Role.viewer)
    detail = (await viewer.get(f"/api/v1/runs/{run.id}")).json()
    assert detail["redacted"] is True and detail["composite_score"] == 64 and detail["composite"]["value"] == 64
    assert detail["scenario"]["content"]["input"] is None and detail["trace"]["output_text"] is None
    assert detail["trace"]["latency_ms"] == 3200
    trace = (await viewer.get(f"/api/v1/runs/{run.id}/trace")).json()
    assert trace["redacted"] and all(e["input"] is None and e["output"] is None for e in trace["events"])
    assert trace["tool_calls"][0]["tool"] == "search" and trace["trace"]["input"] is None
    timeline = (await viewer.get(f"/api/v1/runs/{run.id}/timeline")).json()
    manifest = (await viewer.get(f"/api/v1/runs/{run.id}/manifest")).json()
    for payload in (detail, trace, timeline, manifest):
        assert "confidentiel" not in str(payload).lower(), payload
    listing = (await viewer.get("/api/v1/runs", params={"scenario_id": str(sv.scenario_id)})).json()
    assert listing["items"][0]["composite_score"] == 64

    maintainer = await client_as(Role.maintainer)
    full = (await maintainer.get(f"/api/v1/runs/{run.id}/trace")).json()
    assert full["redacted"] is False and "confidentiel" in str(full).lower()

    evaluator = await client_as(Role.evaluator)
    refused = await evaluator.post(
        f"/api/v1/runs/{run.id}/human-evaluations", json={"scores": [{"criterion_key": "quality.accuracy", "score": 3}]}
    )
    assert refused.status_code == 403
    queue = (await evaluator.get("/api/v1/reviews/queue", params={"page_size": 200})).json()
    assert str(run.id) not in {i["run_id"] for i in queue["items"]}


async def test_scenarios_above_clearance_are_not_revealed(client_as, db_session) -> None:
    sv = await create_scenario_version(db_session)
    scenario = await db_session.get(Scenario, sv.scenario_id)
    scenario.classification = 2
    await db_session.commit()
    low = await client_as(Role.maintainer, clearance=1)
    assert (await low.get(f"/api/v1/scenarios/{scenario.id}")).status_code == 404
    assert (await low.get(f"/api/v1/scenario-versions/{sv.id}")).status_code == 404
    assert (await low.get("/api/v1/scenarios", params={"q": scenario.slug})).json()["total"] == 0
    assert (await low.patch(f"/api/v1/scenarios/{scenario.id}", json={"name": "x"})).status_code == 404
    high = await client_as(Role.viewer, clearance=2)
    detail = (await high.get(f"/api/v1/scenarios/{scenario.id}")).json()
    assert detail["classification_warning"].startswith("Contenu classifié C2")
    creator = await client_as(Role.maintainer, clearance=1)
    response = await creator.post(
        "/api/v1/scenarios",
        json={"name": "Trop haut", "category": "x", "classification": 3, "content": {"input": {"prompt": "x"}}},
    )
    assert response.status_code == 403
