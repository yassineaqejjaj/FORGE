"""Failed run → regression scenario (variant of the scenario carrying the input the run received)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from forge.domain.enums import ErrorSeverity, EvaluatorKind, Role, RunStatus
from forge.infra.models import ExecutionTrace, RunError, Scenario, ScenarioVersion
from tests.factories import attach_trace, create_agent_version, create_run, create_scenario_version


async def _failed_run(db_session, *, with_input: bool = True, failed: bool = True, documents=None):
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av)
    trace = await attach_trace(db_session, run, output_text="réponse incomplète")
    if with_input:
        trace.input = {
            "prompt": "Rembourse mon billet de train",
            "context": {"documents": documents or [{"id": "d1", "content": "x"}]},
        }
    else:
        trace.input = {}
    if failed:
        run.status = RunStatus.failed
        db_session.add(
            RunError(
                run_id=run.id,
                error_type="MISSING_INFORMATION",
                severity=ErrorSeverity.high,
                description="La règle de remboursement est absente",
                evidence=[],
                evaluator_kind=EvaluatorKind.rule,
                evaluator_key="contains",
            )
        )
    else:
        run.status = RunStatus.completed
        run.passed = True
    await db_session.commit()
    return run, sv


async def test_failed_run_becomes_a_regression_variant_and_is_idempotent(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    run, sv = await _failed_run(db_session)
    created = await editor.post(f"/api/v1/runs/{run.id}/promote-to-scenario", json={})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["created"] is True and f"regression_{run.id.hex[:8]}" in body["slug"]

    scenario = await db_session.get(Scenario, uuid.UUID(body["scenario_id"]))
    assert (
        scenario.parent_scenario_id == sv.scenario_id
        and "regression" in scenario.tags
        and f"from-run:{run.id}" in scenario.tags
    )
    version = await db_session.get(ScenarioVersion, uuid.UUID(body["scenario_version_id"]))
    assert version.input["prompt"] == "Rembourse mon billet de train"
    assert version.context["documents"][0]["id"] == "d1"
    assert any("La règle de remboursement est absente" in c for c in version.constraints)
    assert version.rules == sv.rules and version.criteria == sv.criteria  # same yardstick as the original

    again = await editor.post(f"/api/v1/runs/{run.id}/promote-to-scenario", json={})
    assert again.status_code == 200 and again.json()["created"] is False
    assert again.json()["scenario_id"] == body["scenario_id"]
    count = len(list(await db_session.scalars(select(Scenario).where(Scenario.slug == body["slug"]))))
    assert count == 1


async def test_only_failed_runs_with_a_recorded_input_can_be_promoted(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    ok_run, _ = await _failed_run(db_session, failed=False)
    assert (await editor.post(f"/api/v1/runs/{ok_run.id}/promote-to-scenario")).status_code == 422
    blank, _ = await _failed_run(db_session, with_input=False)
    assert (await editor.post(f"/api/v1/runs/{blank.id}/promote-to-scenario", json={})).status_code == 422
    viewer = await client_as(Role.viewer)
    run, _ = await _failed_run(db_session)
    assert (await viewer.post(f"/api/v1/runs/{run.id}/promote-to-scenario")).status_code == 403
    assert (await editor.post(f"/api/v1/runs/{uuid.uuid4()}/promote-to-scenario")).status_code == 404
    trace = await db_session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id))
    assert trace is not None


async def test_promotion_never_launders_a_classified_document_into_a_lower_scenario(
    client_as, db_session
) -> None:
    """A C3 ORBIT document copied into the regression scenario makes that scenario C3 (never the parent's C1)."""
    documents = [
        {"id": "d1", "content": "public interne", "classification": 1},
        {"id": "d2", "content": "remise synthétique 35 %", "classification": 3},
    ]
    run, sv = await _failed_run(db_session, documents=documents)
    parent = await db_session.get(Scenario, sv.scenario_id)
    assert parent.classification == 1

    low = await client_as(Role.editor, clearance=1)
    assert (await low.post(f"/api/v1/runs/{run.id}/promote-to-scenario", json={})).status_code == 403

    high = await client_as(Role.editor, clearance=3)
    created = await high.post(f"/api/v1/runs/{run.id}/promote-to-scenario", json={})
    assert created.status_code == 201, created.text
    scenario = await db_session.get(Scenario, uuid.UUID(created.json()["scenario_id"]))
    assert scenario.classification == 3
    assert (await low.get(f"/api/v1/scenarios/{scenario.id}")).status_code == 404  # not visible at C1


async def test_promotion_keeps_the_parents_classification_when_documents_are_lower(
    client_as, db_session
) -> None:
    run, sv = await _failed_run(db_session)
    parent = await db_session.get(Scenario, sv.scenario_id)
    parent.classification = 2
    await db_session.commit()
    editor = await client_as(Role.editor, clearance=2)
    created = await editor.post(f"/api/v1/runs/{run.id}/promote-to-scenario", json={})
    assert created.status_code == 201, created.text
    scenario = await db_session.get(Scenario, uuid.UUID(created.json()["scenario_id"]))
    assert scenario.classification == 2
