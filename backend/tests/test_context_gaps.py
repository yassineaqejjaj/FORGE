"""Context-gap loop: a run that failed for lack of information → ORBIT completes the context → re-test."""

from __future__ import annotations

import json
import uuid

import httpx
import respx
from sqlalchemy import select

from forge.domain.enums import ErrorSeverity, EvaluatorKind, ProviderKind, Role
from forge.infra.models import AgentVersion, AuditEvent, EvaluationRun, RunError
from forge.services.credentials import create_credential
from tests.factories import create_agent_version, create_run, create_scenario_version

ORBIT = "https://orbit.example"
REQUEST_ID = "5d0f9c3e-0a3c-4c43-a1a0-2f6f4f0b7a11"
COMPLETION = {
    "request_id": "9a9a9a9a-0000-4000-8000-000000000001",
    "completes": REQUEST_ID,
    "snapshot": {"id": "2c2c2c2c-0000-4000-8000-000000000002", "name": "atlas", "version": 5},
    "added": [{"citation": "S4", "id": "chunk-9", "title": "Règle de remboursement", "classification": 1}],
    "still_missing": [],
    "tokens_used": 812,
}


async def _failed_run(db_session, *, manifest=None, with_error=True, context_config=None):
    av = await create_agent_version(db_session)
    if context_config is not None:
        av_row = await db_session.get(AgentVersion, av.id)
        av_row.context_config = context_config
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av)
    run.source_manifest = manifest
    if with_error:
        db_session.add(
            RunError(
                run_id=run.id,
                error_type="MISSING_INFORMATION",
                severity=ErrorSeverity.high,
                description="La règle de remboursement des frais de transport est absente de la réponse",
                evidence=[],
                evaluator_kind=EvaluatorKind.rule,
                evaluator_key="contains",
            )
        )
    await db_session.commit()
    return run


async def _credential(db_session) -> uuid.UUID:
    credential = await create_credential(
        db_session,
        name=f"orbit-{uuid.uuid4().hex[:6]}",
        kind=ProviderKind.orbit,
        secret="orbit-key-1",
        base_url=ORBIT,
    )
    await db_session.commit()
    return credential.id


MANIFEST = {"context": {"retrieval_id": REQUEST_ID, "project_slug": "atlas", "snapshot_id": "atlas@v4"}}


@respx.mock
async def test_missing_information_is_sent_to_orbit_and_the_run_is_retested(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    run = await _failed_run(db_session, manifest=MANIFEST)
    credential = await _credential(db_session)
    route = respx.post(f"{ORBIT}/api/v1/projects/atlas/context/requests/{REQUEST_ID}/complete").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )
    response = await editor.post(
        f"/api/v1/runs/{run.id}/context-gap", json={"credential_id": str(credential), "retest": True}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"missing": ["La règle de remboursement des frais de transport est absente de la réponse"]}
    assert route.calls.last.request.headers["authorization"] == "Bearer orbit-key-1"
    assert body["orbit_request_id"] == REQUEST_ID and body["orbit_project"] == "atlas"
    assert (
        body["completion"]["snapshot"]["version"] == 5 and body["completion"]["added"][0]["id"] == "chunk-9"
    )

    # A candidate version pinned to the new snapshot, and the same scenario run against it.
    candidate = await db_session.get(AgentVersion, uuid.UUID(body["candidate_version_id"]))
    assert candidate.context_config["source"] == "orbit_snapshot"
    assert (
        candidate.context_config["orbit"]["snapshot"] == "atlas"
        and candidate.context_config["orbit"]["version"] == "5"
    )
    retest = await db_session.get(EvaluationRun, uuid.UUID(body["retest_run_id"]))
    assert retest.agent_version_id == candidate.id and retest.scenario_version_id == run.scenario_version_id
    assert retest.context_snapshot_id == "atlas@v5" and f"context-gap-of:{run.id}" in retest.tags
    assert retest.source_manifest["context_gap_of"] == str(run.id)
    audit = await db_session.scalar(select(AuditEvent).where(AuditEvent.action == "run.context_gap"))
    assert audit is not None


@respx.mock
async def test_explicit_gaps_without_retest_create_nothing_else(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    run = await _failed_run(db_session, manifest=MANIFEST, with_error=False)
    credential = await _credential(db_session)
    route = respx.post(f"{ORBIT}/api/v1/projects/atlas/context/requests/{REQUEST_ID}/complete").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )
    response = await editor.post(
        f"/api/v1/runs/{run.id}/context-gap",
        json={
            "missing": ["Délai de rétractation"],
            "snapshot": "atlas-gap",
            "credential_id": str(credential),
        },
    )
    assert response.status_code == 200, response.text
    assert json.loads(route.calls.last.request.content) == {
        "missing": ["Délai de rétractation"],
        "snapshot": {"name": "atlas-gap"},
    }
    assert response.json()["candidate_version_id"] is None and response.json()["retest_run_id"] is None


@respx.mock
async def test_refusals(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    no_gap = await _failed_run(db_session, manifest=MANIFEST, with_error=False)
    assert (
        await editor.post(f"/api/v1/runs/{no_gap.id}/context-gap", json={})
    ).status_code == 422  # nothing missing
    no_orbit = await _failed_run(db_session, manifest=None)
    assert (
        await editor.post(f"/api/v1/runs/{no_orbit.id}/context-gap", json={})
    ).status_code == 422  # no request
    unreachable = await _failed_run(db_session, manifest=MANIFEST)
    respx.post(f"{ORBIT}/api/v1/projects/atlas/context/requests/{REQUEST_ID}/complete").mock(
        return_value=httpx.Response(404, json={"detail": "introuvable"})
    )
    credential = await _credential(db_session)
    failed = await editor.post(
        f"/api/v1/runs/{unreachable.id}/context-gap", json={"credential_id": str(credential)}
    )
    assert failed.status_code == 409 and "ORBIT" in failed.text
    viewer = await client_as(Role.viewer)
    assert (await viewer.post(f"/api/v1/runs/{unreachable.id}/context-gap", json={})).status_code == 403
    assert (await editor.post(f"/api/v1/runs/{uuid.uuid4()}/context-gap", json={})).status_code == 404
