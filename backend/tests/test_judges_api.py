"""Judges API: versions (409 on identical), validation, enable/disable, dry-run test, roles."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role
from forge.services import runs as run_service
from tests.conftest import run_jobs
from tests.factories import attach_trace, create_agent_version, create_run, create_scenario_version


def _key() -> str:
    return f"judge-{uuid.uuid4().hex[:8]}"


async def test_create_version_and_conflict(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    key = _key()
    body = {
        "key": key,
        "name": "Juge maison",
        "provider": "heuristic",
        "model": "heuristic-v1",
        "criteria": ["ux.clarity"],
    }
    created = await maintainer.post("/api/v1/judges", json=body)
    assert created.status_code == 201, created.text
    v1 = created.json()
    assert v1["version"] == 1 and v1["is_latest"] and v1["content_hash"].startswith("sha256:")
    assert "output" in v1["placeholders"] and v1["system_prompt"]
    assert (await maintainer.post("/api/v1/judges", json=body)).status_code == 409
    same = await maintainer.post(f"/api/v1/judges/{v1['id']}/versions", json={"criteria": ["ux.clarity"]})
    assert same.status_code == 409
    v2 = await maintainer.post(
        f"/api/v1/judges/{v1['id']}/versions", json={"criteria": ["ux.clarity", "quality.accuracy"]}
    )
    assert v2.status_code == 201 and v2.json()["version"] == 2
    assert [v["version"] for v in v2.json()["versions"]] == [2, 1]
    old = (await maintainer.get(f"/api/v1/judges/{v1['id']}")).json()
    assert old["is_latest"] is False
    listing = (await maintainer.get("/api/v1/judges", params={"key": key})).json()
    assert listing["total"] == 2
    latest = (await maintainer.get("/api/v1/judges", params={"q": key})).json()
    assert [j["version"] for j in latest["items"]] == [2]


async def test_validation_errors(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    cases = [
        {"criteria": ["cost.tokens"]},
        {"criteria": ["unknown.criterion"]},
        {"rubric_template": "Évalue {output} et {inconnu}"},
        {"provider": "anthropic", "model": "claude-haiku-4-5"},  # no credential
        {"credential_id": str(uuid.uuid4()), "provider": "openai", "model": "gpt-4.1"},
    ]
    for extra in cases:
        body = {"key": _key(), "name": "J", "provider": "heuristic", "model": "heuristic-v1", **extra}
        response = await maintainer.post("/api/v1/judges", json=body)
        assert response.status_code == 422, (extra, response.text)
        assert response.json()["code"] == "validation_error"


async def test_roles_and_enable(client_as) -> None:
    viewer = await client_as(Role.viewer)
    body = {"key": _key(), "name": "J", "provider": "heuristic", "model": "heuristic-v1"}
    assert (await viewer.post("/api/v1/judges", json=body)).status_code == 403
    editor = await client_as(Role.editor)
    assert (await editor.post("/api/v1/judges", json=body)).status_code == 403
    maintainer = await client_as(Role.maintainer)
    judge = (await maintainer.post("/api/v1/judges", json=body)).json()
    disabled = await maintainer.patch(
        f"/api/v1/judges/{judge['id']}", json={"enabled": False, "name": "Renommé"}
    )
    assert (
        disabled.status_code == 200
        and disabled.json()["enabled"] is False
        and disabled.json()["name"] == "Renommé"
    )
    assert disabled.json()["version"] == 1  # metadata only
    assert (await viewer.get(f"/api/v1/judges/{judge['id']}")).status_code == 200
    assert (await viewer.get(f"/api/v1/judges/{uuid.uuid4()}")).status_code == 404


async def test_dry_run_on_existing_run(db_session, client_as) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av)
    await attach_trace(db_session, run, output_text="# Objectifs\nUn PRD pour l'export CSV.")
    await run_service.mark_evaluating(db_session, run)
    await db_session.commit()
    await run_jobs()
    maintainer = await client_as(Role.maintainer)
    judge = (
        await maintainer.post(
            "/api/v1/judges",
            json={"key": _key(), "name": "J", "provider": "heuristic", "model": "heuristic-v1"},
        )
    ).json()
    before = (await maintainer.get(f"/api/v1/runs/{run.id}/evaluations")).json()["items"]
    response = await maintainer.post(
        f"/api/v1/judges/{judge['id']}/test",
        json={"run_id": str(run.id), "criteria": ["quality.accuracy", "ux.clarity"]},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "ok" and data["persisted"] is False
    assert [v["criterion_key"] for v in data["verdicts"]] == ["quality.accuracy", "ux.clarity"]
    assert (
        data["prompt"]["prompt_hash"].startswith("sha256:") and "Critères à évaluer" in data["prompt"]["user"]
    )
    after = (await maintainer.get(f"/api/v1/runs/{run.id}/evaluations")).json()["items"]
    assert len(after) == len(before)
    viewer = await client_as(Role.viewer)
    assert (
        await viewer.post(f"/api/v1/judges/{judge['id']}/test", json={"run_id": str(run.id)})
    ).status_code == 403
