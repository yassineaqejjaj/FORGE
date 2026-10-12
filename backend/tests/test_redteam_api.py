"""Red team API: install the catalogue once, launch it against an agent version, read the resistance."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from forge.domain import redteam
from forge.domain.enums import Role
from forge.infra.models import EvaluationRun, Scenario, ScenarioVersion
from tests.factories import complete_with_scores, create_agent_version


async def _attack_of(db_session, run_id: str) -> str:
    slug = await db_session.scalar(
        select(Scenario.slug)
        .join(ScenarioVersion, ScenarioVersion.scenario_id == Scenario.id)
        .join(EvaluationRun, EvaluationRun.scenario_version_id == ScenarioVersion.id)
        .where(EvaluationRun.id == uuid.UUID(run_id))
    )
    attack = redteam.attack_for_slug(slug or "")
    assert attack is not None
    return attack.key


async def test_launching_installs_the_catalogue_once_and_runs_every_attack(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    await db_session.commit()
    editor = await client_as(Role.editor)

    first = await editor.post("/api/v1/redteam/runs", json={"agent_version_id": str(av.id)})
    assert first.status_code == 201, first.text
    assert first.json()["attacks"] == len(redteam.CATALOG) == len(first.json()["run_ids"])
    again = await editor.post("/api/v1/redteam/runs", json={"agent_version_id": str(av.id), "repetitions": 2})
    assert again.status_code == 201 and len(again.json()["run_ids"]) == 2 * len(redteam.CATALOG)

    catalog = (await editor.get("/api/v1/redteam/catalog")).json()
    assert [a["key"] for a in catalog] == [a.key for a in redteam.CATALOG]
    assert all(a["scenario_id"] for a in catalog)
    count = await db_session.scalar(
        select(Scenario.id).where(Scenario.slug == redteam.BY_KEY["tool_abuse"].slug).limit(1)
    )
    assert count is not None
    scenarios = (
        await db_session.scalars(select(Scenario.slug).where(Scenario.category == redteam.CATEGORY))
    ).all()
    assert len(scenarios) == len(set(scenarios))  # one scenario per attack, however many launches


async def test_viewers_can_read_but_not_launch(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    await db_session.commit()
    viewer = await client_as(Role.viewer)
    assert (
        await viewer.post("/api/v1/redteam/runs", json={"agent_version_id": str(av.id)})
    ).status_code == 403
    assert (await viewer.get("/api/v1/redteam/catalog")).status_code == 200
    assert (
        await viewer.get("/api/v1/redteam/report", params={"agent_version_id": str(uuid.uuid4())})
    ).status_code == 404


async def test_the_report_grades_each_family_from_the_rules_that_fired(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    await db_session.commit()
    editor = await client_as(Role.editor)
    empty = (await editor.get("/api/v1/redteam/report", params={"agent_version_id": str(av.id)})).json()
    assert empty["status"] == "not_run" and empty["resistance"] is None

    run_ids = (await editor.post("/api/v1/redteam/runs", json={"agent_version_id": str(av.id)})).json()[
        "run_ids"
    ]
    for run_id in run_ids:
        run = await db_session.get(EvaluationRun, uuid.UUID(run_id))
        assert run is not None
        leaked = await _attack_of(db_session, run_id) == "confidential_exfiltration"
        await complete_with_scores(
            db_session, run, composite=80.0, errors=[("DATA_LEAK", "high")] if leaked else None
        )
    await db_session.commit()

    report = (await editor.get("/api/v1/redteam/report", params={"agent_version_id": str(av.id)})).json()
    families = {f["key"]: f for f in report["families"]}
    assert report["status"] == "vulnerable" and report["resistance"] == round(
        (len(redteam.CATALOG) - 1) / len(redteam.CATALOG), 4
    )
    assert (
        families["confidential_exfiltration"]["status"] == "weak"
        and families["confidential_exfiltration"]["resistance"] == 0.0
    )
    assert families["confidential_exfiltration"]["error_types"] == {"DATA_LEAK": 1}
    assert len(families["confidential_exfiltration"]["failed_run_ids"]) == 1
    assert (
        families["prompt_injection"]["status"] == "solid"
        and families["prompt_injection"]["resistance"] == 1.0
    )
