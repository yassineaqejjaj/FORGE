"""Observed runs (``POST /runs/observed``): ingestion, idempotency, access, deterministic scoring from
``output_json`` with the definitions documented in docs/OBSERVED_RUNS.md, failed executions."""

from __future__ import annotations

import asyncio
import copy
import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select

from forge.domain.enums import EvaluatorKind, JobKind, Role, RunOrigin, RunStatus, TraceEventType
from forge.domain.rules import evaluate_rules
from forge.infra.models import (
    AuditEvent,
    CompositeScore,
    Evaluation,
    EvaluationRun,
    ExecutionTrace,
    Job,
    RunError,
    Scenario,
    TraceEvent,
)
from forge.services.mapping import specs_from_manifest
from tests.conftest import run_jobs
from tests.factories import create_agent_version, create_scenario_version
from tests.unit.test_rules import make_ctx

DOC = Path(__file__).resolve().parents[2] / "docs" / "OBSERVED_RUNS.md"
URL = "/api/v1/runs/observed"
PLACEHOLDER_AGENT_VERSION = "11111111-1111-4111-8111-111111111111"
PLACEHOLDER_SCENARIO = "22222222-2222-4222-8222-222222222222"
PLACEHOLDER_CONFIG = "33333333-3333-4333-8333-333333333333"


def doc_example(name: str) -> dict[str, Any]:
    """JSON block following ``<!-- example: <name> -->`` in docs/OBSERVED_RUNS.md (deep copy)."""
    if not DOC.exists():
        pytest.skip("docs/OBSERVED_RUNS.md absent (tests lancés hors du dépôt)")
    match = re.search(rf"<!-- example: {name} -->\s*```json\n(.*?)\n```", DOC.read_text(), re.DOTALL)
    assert match, f"exemple « {name} » introuvable dans {DOC.name}"
    return json.loads(match.group(1))


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def create_nova_scenario(client, **overrides: Any) -> dict[str, Any]:
    body = doc_example("scenario") | {"slug": unique("nova-sdlc")} | overrides
    response = await client.post("/api/v1/scenarios", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def create_nova_config(client) -> dict[str, Any]:
    body = doc_example("evaluation_config") | {"key": unique("nova-delivery")}
    response = await client.post("/api/v1/evaluation-configs", json=body)
    assert response.status_code == 201, response.text
    config = response.json()
    assert config["is_default"] is False and config["judge_ids"] == []
    return config


def observed_body(agent_version_id, scenario_id, config_id=None, **overrides: Any) -> dict[str, Any]:
    body = doc_example("request")
    body.update(
        agent_version_id=str(agent_version_id),
        scenario_id=str(scenario_id),
        evaluation_config_id=str(config_id) if config_id else None,
        external_id=unique("nova-sdlc"),
    )
    body.update(overrides)
    return body


async def evaluated(client, run_id: str) -> dict[str, Any]:
    await run_jobs()
    detail = await client.get(f"/api/v1/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()


# =====================================================================================================
# Ingestion
# =====================================================================================================


async def test_observed_run_is_scored_by_the_documented_rules(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    maintainer = await client_as(Role.maintainer)
    scenario = await create_nova_scenario(editor)
    config = await create_nova_config(maintainer)
    av = await create_agent_version(db_session, name="NOVA SDLC")
    await db_session.commit()

    body = observed_body(av.id, scenario["id"], config["id"])
    response = await editor.post(URL, json=body)
    assert response.status_code == 201, response.text
    run = response.json()
    assert (
        run["origin"] == "observed"
        and run["status"] == "evaluating"
        and run["external_id"] == body["external_id"]
    )
    assert run["tags"] == ["nova", "sdlc"] and run["evaluation_config_id"] == config["id"]
    assert run["scenario_id"] == scenario["id"] and run["scenario_version"] == 1
    assert run["latency_ms"] == 2_530_000.0 and run["total_tokens"] == 205_000
    assert set(doc_example("response")) == set(run), (
        "l'exemple de réponse de la doc doit lister les mêmes champs"
    )

    # Built like an ad-hoc run: frozen manifest, no execution job, evaluation queued.
    row = await db_session.get(EvaluationRun, uuid.UUID(run["id"]))
    assert row.origin == RunOrigin.observed and row.manifest["scenario"]["rules"]
    assert specs_from_manifest(row.manifest).config.key == config["key"]
    jobs = list(await db_session.scalars(select(Job).where(Job.run_id == row.id)))
    assert [j.kind for j in jobs] == [JobKind.evaluate_run]
    trace = await db_session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == row.id))
    assert trace.output_json["merged"] is True and trace.input["prompt"].startswith("Ajouter l'export")
    assert (trace.input_tokens, trace.output_tokens, trace.model_calls) == (184_000, 21_000, 37)
    events = list(
        await db_session.scalars(
            select(TraceEvent).where(TraceEvent.run_id == row.id).order_by(TraceEvent.seq)
        )
    )
    assert [e.type for e in events] == [
        TraceEventType.run_started,
        TraceEventType.final_answer,
        TraceEventType.run_completed,
    ]
    assert events[-1].offset_ms == 2_530_000.0 and trace.event_count == 3
    audit_row = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "run.observe", AuditEvent.target_id == run["id"])
    )
    assert audit_row is not None

    # The normal evaluate_run job scores it from the rules only (no judge).
    detail = await evaluated(editor, run["id"])
    assert detail["status"] == "completed" and detail["evaluation_round"] == 1
    assert detail["passed"] is True and detail["gate_failed"] is False
    # delivered 3 + merged 3 + ci_first_pass 0/2 + no_review_fixes 1 = 7/9 of quality, autonomy 1.0
    expected = 100 * (0.8 * 7 / 9 + 0.2 * 1.0)
    assert detail["composite_score"] == pytest.approx(expected, abs=1e-3)
    assert detail["composite"]["value"] == detail["composite_score"] and detail["composite"]["formula"]
    assert detail["trace"]["output_json"]["merged"] is True

    scores = (await editor.get(f"/api/v1/runs/{run['id']}/scores")).json()
    by_key = {s["criterion_key"]: s for s in scores["scores"] if s["source"] == "rule"}
    assert {k: v["value"] for k, v in by_key.items()} == {
        "quality.delivered": 1.0,
        "quality.merged": 1.0,
        "quality.ci_first_pass": 0.0,
        "quality.no_review_fixes_needed": 1.0,
        "ux.autonomy": 1.0,
    }
    assert by_key["quality.delivered"]["weight"] == 3 and by_key["quality.ci_first_pass"]["weight"] == 2
    assert all(s["explanation"] for s in by_key.values())
    assert scores["composite"]["value"] == detail["composite_score"]
    assert "Aucun juge actif" in (detail["status_detail"] or "")
    kinds = {
        e.evaluator_kind
        for e in await db_session.scalars(select(Evaluation).where(Evaluation.run_id == row.id))
    }
    assert EvaluatorKind.llm_judge not in kinds and EvaluatorKind.rule in kinds
    errors = (await editor.get(f"/api/v1/runs/{run['id']}/errors")).json()["items"]
    assert [e["criterion_key"] for e in errors] == ["quality.ci_first_pass"]

    # Trace endpoint, listing filters and the retry guard.
    trace_out = (await editor.get(f"/api/v1/runs/{run['id']}/trace")).json()
    assert [e["type"] for e in trace_out["events"]] == ["run_started", "final_answer", "run_completed"]
    listing = (
        await editor.get("/api/v1/runs", params={"origin": "observed", "external_id": body["external_id"]})
    ).json()
    assert [r["id"] for r in listing["items"]] == [run["id"]]
    assert listing["items"][0]["composite_score"] == detail["composite_score"]
    assert (await editor.post(f"/api/v1/runs/{run['id']}/retry")).status_code == 409


async def test_unmerged_run_is_capped_below_the_pass_threshold(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    config = await create_nova_config(await client_as(Role.maintainer))
    av = await create_agent_version(db_session)
    await db_session.commit()
    output = doc_example("request")["output_json"] | {
        "merged": False,
        "first_pass_ci": True,
        "review_fix_rounds": 3,
        "human_interventions": 5,
    }
    response = await editor.post(
        URL, json=observed_body(av.id, scenario["id"], config["id"], output_json=output)
    )
    run = await evaluated(editor, response.json()["id"])
    # delivered 3 + ci 2 = 5/9 quality, autonomy 0 → 44.4: under the cap anyway; the gate is reported.
    assert run["status"] == "completed" and run["passed"] is False
    assert run["composite_score"] == pytest.approx(100 * 0.8 * 5 / 9, abs=1e-3)
    gates = {g["gate_id"]: g for g in run["composite"]["gates"]}
    assert gates["must-be-merged"]["passed"] is False
    # Same output but everything else perfect: the cap (60) keeps it from passing.
    perfect = output | {"first_pass_ci": True, "review_fix_rounds": 0, "human_interventions": 0}
    capped = await editor.post(
        URL, json=observed_body(av.id, scenario["id"], config["id"], output_json=perfect)
    )
    run2 = await evaluated(editor, capped.json()["id"])
    assert run2["composite_score"] == 60 and run2["passed"] is False
    assert "plafonné à 60" in run2["composite"]["formula"]


async def test_default_configuration_when_none_given(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    response = await editor.post(URL, json=observed_body(av.id, scenario["id"], None))
    assert response.status_code == 201, response.text
    run = await evaluated(editor, response.json()["id"])
    assert run["evaluation_config"]["key"] == "forge-default"
    assert run["status"] == "completed" and run["composite_score"] is not None
    scores = (await editor.get(f"/api/v1/runs/{run['id']}/scores")).json()
    assert {"rule", "metric"} <= {s["source"] for s in scores["scores"]}
    assert scores["composite"] is not None


async def test_uses_the_current_scenario_version(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    version = await editor.post(
        f"/api/v1/scenarios/{scenario['id']}/versions",
        json={"content": {"expected_behavior": "Deuxième version."}, "changelog": "v2"},
    )
    assert version.status_code == 201, version.text
    response = await editor.post(URL, json=observed_body(av.id, scenario["id"]))
    assert response.status_code == 201 and response.json()["scenario_version"] == 2
    assert response.json()["scenario_version_id"] == version.json()["id"]


# =====================================================================================================
# Idempotency
# =====================================================================================================


async def test_same_external_id_returns_the_existing_run(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    other_version = await create_agent_version(
        db_session, agent=await _agent_of(db_session, av), version="2.0"
    )
    other_agent = await create_agent_version(db_session)
    await db_session.commit()
    body = observed_body(av.id, scenario["id"])
    first = await editor.post(URL, json=body)
    assert first.status_code == 201, first.text
    again = await editor.post(URL, json=body | {"output_text": "autre contenu", "tags": ["x"]})
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"] and again.json()["tags"] == ["nova", "sdlc"]
    # Unique per agent, not per version: another version of the same agent gets the same run back.
    same_agent = await editor.post(URL, json=body | {"agent_version_id": str(other_version.id)})
    assert same_agent.status_code == 200 and same_agent.json()["id"] == first.json()["id"]
    # A different agent may reuse the key.
    different = await editor.post(URL, json=body | {"agent_version_id": str(other_agent.id)})
    assert different.status_code == 201 and different.json()["id"] != first.json()["id"]
    rows = list(
        await db_session.scalars(
            select(EvaluationRun).where(EvaluationRun.external_id == body["external_id"])
        )
    )
    assert len(rows) == 2
    jobs = list(await db_session.scalars(select(Job).where(Job.run_id == uuid.UUID(first.json()["id"]))))
    assert len(jobs) == 1, "no second evaluation job"


async def _agent_of(session, av):
    from forge.infra.models import Agent

    return await session.get(Agent, av.agent_id)


async def test_concurrent_calls_with_the_same_external_id_create_one_run(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    body = observed_body(av.id, scenario["id"])
    responses = await asyncio.gather(*(editor.post(URL, json=body) for _ in range(4)))
    assert sorted(r.status_code for r in responses) == [200, 200, 200, 201], [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    rows = list(
        await db_session.scalars(
            select(EvaluationRun).where(EvaluationRun.external_id == body["external_id"])
        )
    )
    assert len(rows) == 1


# =====================================================================================================
# Access and validation
# =====================================================================================================


async def test_role_and_authentication(client_as, client, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    body = observed_body(av.id, scenario["id"])
    assert (await (await client_as(Role.viewer)).post(URL, json=body)).status_code == 403
    assert (await (await client_as(Role.evaluator)).post(URL, json=body)).status_code == 403
    assert (await client.post(URL, json=body)).status_code == 401
    assert (await (await client_as(Role.maintainer)).post(URL, json=body)).status_code == 201


async def test_api_key_with_editor_role_can_ingest(admin_client, client_as, db_session) -> None:
    scenario = await create_nova_scenario(await client_as(Role.editor))
    av = await create_agent_version(db_session)
    await db_session.commit()
    created = await admin_client.post("/api/v1/api-keys", json={"name": "NOVA", "role": "editor"})
    key = created.json()["key"]
    body = observed_body(av.id, scenario["id"])
    headers = {"X-Forge-Key": key, "Authorization": ""}
    first = await admin_client.post(URL, json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert (await admin_client.post(URL, json=body, headers=headers)).status_code == 200
    viewer_key = (await admin_client.post("/api/v1/api-keys", json={"name": "ro", "role": "viewer"})).json()[
        "key"
    ]
    denied = await admin_client.post(URL, json=body, headers={"X-Forge-Key": viewer_key, "Authorization": ""})
    assert denied.status_code == 403
    row = await db_session.get(EvaluationRun, uuid.UUID(first.json()["id"]))
    assert row.created_by is None


async def test_scenario_above_clearance_is_not_revealed(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    scenario = await db_session.get(Scenario, sv.scenario_id)
    scenario.classification = 2
    await db_session.commit()
    body = observed_body(av.id, scenario.id)
    low = await client_as(Role.editor, clearance=1)
    refused = await low.post(URL, json=body)
    assert refused.status_code == 404, refused.text
    high = await client_as(Role.editor, clearance=2)
    created = await high.post(URL, json=body)
    assert created.status_code == 201 and created.json()["classification"] == 2
    # An existing run of a hidden scenario is not revealed by a replay either.
    assert (await low.post(URL, json=body)).status_code == 404
    assert (await high.post(URL, json=body)).status_code == 200


async def test_unknown_or_archived_references(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    assert (await editor.post(URL, json=observed_body(uuid.uuid4(), scenario["id"]))).status_code == 404
    assert (await editor.post(URL, json=observed_body(av.id, uuid.uuid4()))).status_code == 404
    assert (
        await editor.post(URL, json=observed_body(av.id, scenario["id"], uuid.uuid4()))
    ).status_code == 404
    archived = await editor.patch(f"/api/v1/scenarios/{scenario['id']}", json={"archived": True})
    assert archived.status_code == 200, archived.text
    response = await editor.post(URL, json=observed_body(av.id, scenario["id"]))
    assert response.status_code == 422 and "archivé" in response.json()["detail"]


async def test_payload_validation(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()

    def body(**overrides: Any) -> dict[str, Any]:
        return observed_body(av.id, scenario["id"], **overrides)

    assert (await editor.post(URL, json=body(completed_at="2026-10-09T07:00:00Z"))).status_code == 422
    assert (await editor.post(URL, json=body(started_at="2026-10-09T08:00:00"))).status_code == 422
    assert (await editor.post(URL, json=body(execution_status="running"))).status_code == 422
    assert (await editor.post(URL, json=body(error="oups"))).status_code == 422  # error on a completed run
    assert (await editor.post(URL, json=body(external_id="  "))).status_code == 422
    assert (await editor.post(URL, json=body(usage={"input_tokens": -1}))).status_code == 422
    assert (await editor.post(URL, json=body(output_json=["pas", "un", "objet"]))).status_code == 422
    missing = body()
    del missing["external_id"]
    assert (await editor.post(URL, json=missing)).status_code == 422
    minimal = {
        "agent_version_id": str(av.id),
        "scenario_id": scenario["id"],
        "input": {"prompt": "x"},
        "execution_status": "completed",
        "started_at": "2026-10-09T08:00:00+02:00",
        "completed_at": "2026-10-09T06:00:01Z",
        "external_id": unique("min"),
    }
    ok = await editor.post(URL, json=minimal)
    assert ok.status_code == 201, ok.text
    assert ok.json()["latency_ms"] == 1000.0 and ok.json()["tags"] == [] and ok.json()["total_tokens"] == 0
    deduped = await editor.post(
        URL, json=minimal | {"external_id": unique("tags"), "tags": [" a ", "a", "", "b"]}
    )
    assert deduped.json()["tags"] == ["a", "b"]


# =====================================================================================================
# Failed execution
# =====================================================================================================


async def test_failed_execution_is_recorded_and_scores_zero(client_as, db_session) -> None:
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    output = {
        "outcome": "failed",
        "merged": False,
        "first_pass_ci": False,
        "review_fix_rounds": 0,
        "human_interventions": 0,
    }
    response = await editor.post(
        URL,
        json=observed_body(
            av.id,
            scenario["id"],
            execution_status="failed",
            error="CI rouge après 3 tentatives",
            output_json=output,
            output_text=None,
        ),
    )
    assert response.status_code == 201, response.text
    run_id = response.json()["id"]
    assert response.json()["error_type"] == "EXECUTION_ERROR" and response.json()["status"] == "evaluating"
    run = await evaluated(editor, run_id)
    assert run["status"] == "failed" and run["error"] == "CI rouge après 3 tentatives"
    assert run["composite_score"] == 0 and run["passed"] is False and run["evaluation_round"] == 1
    assert "exécution de l'agent en échec" in run["composite"]["formula"]
    assert run["trace"]["errors"][0]["message"] == "CI rouge après 3 tentatives"
    assert run["trace"]["output_json"]["outcome"] == "failed", "reported outputs are kept for diagnosis"
    errors = list(await db_session.scalars(select(RunError).where(RunError.run_id == uuid.UUID(run_id))))
    assert [e.error_type for e in errors if e.round is None] == ["EXECUTION_ERROR"]
    kinds = {
        e.evaluator_kind
        for e in await db_session.scalars(select(Evaluation).where(Evaluation.run_id == uuid.UUID(run_id)))
    }
    assert EvaluatorKind.llm_judge not in kinds and EvaluatorKind.rule in kinds
    composite = await db_session.scalar(
        select(CompositeScore).where(CompositeScore.run_id == uuid.UUID(run_id))
    )
    assert composite.value == 0
    events = (await editor.get(f"/api/v1/runs/{run_id}/trace")).json()["events"]
    assert [e["type"] for e in events] == ["run_started", "error", "run_completed"]
    assert events[1]["status"] == "error"

    default_message = await editor.post(
        URL, json=observed_body(av.id, scenario["id"], execution_status="failed", error=None)
    )
    assert default_message.status_code == 201
    failed = await evaluated(editor, default_message.json()["id"])
    assert failed["status"] == "failed" and "rapportée par le système externe" in failed["error"]


# =====================================================================================================
# Documented rules (pure)
# =====================================================================================================

DELIVERED = {
    "outcome": "completed",
    "merged": True,
    "first_pass_ci": True,
    "review_fix_rounds": 0,
    "human_interventions": 2,
}


def _rule_values(output_json: dict[str, Any]) -> dict[str, float]:
    from forge.services.mapping import parse_rules

    rules = parse_rules(doc_example("scenario")["content"]["rules"])
    results = evaluate_rules(make_ctx("", output_json=output_json), rules)
    assert all(
        r.evaluator_kind == EvaluatorKind.rule and not r.raw_response["misconfigured"] for r in results
    )
    return {r.criterion_key: r.normalized for r in results}


@pytest.mark.parametrize(
    ("changes", "failing"),
    [
        ({}, set()),
        ({"outcome": "failed"}, {"quality.delivered"}),
        ({"merged": False}, {"quality.merged"}),
        ({"first_pass_ci": False}, {"quality.ci_first_pass"}),
        ({"review_fix_rounds": 1}, {"quality.no_review_fixes_needed"}),
        ({"human_interventions": 0}, set()),
        ({"human_interventions": 3}, {"ux.autonomy"}),
        ({"human_interventions": 2.5}, {"ux.autonomy"}),
        ({"merged": "true"}, {"quality.merged"}),
    ],
)
def test_documented_rules_on_output_json(changes: dict[str, Any], failing: set[str]) -> None:
    values = _rule_values(DELIVERED | changes)
    assert {k for k, v in values.items() if v == 0.0} == failing
    assert len(values) == 5


def test_documented_rules_fail_when_a_key_is_missing() -> None:
    for key, criterion in (
        ("outcome", "quality.delivered"),
        ("merged", "quality.merged"),
        ("first_pass_ci", "quality.ci_first_pass"),
        ("review_fix_rounds", "quality.no_review_fixes_needed"),
        ("human_interventions", "ux.autonomy"),
    ):
        partial = copy.deepcopy(DELIVERED)
        del partial[key]
        assert _rule_values(partial)[criterion] == 0.0, key


def test_doc_request_example_is_consistent_with_the_documented_rules() -> None:
    request = doc_example("request")
    assert request["agent_version_id"] == PLACEHOLDER_AGENT_VERSION
    assert request["scenario_id"] == PLACEHOLDER_SCENARIO
    assert request["evaluation_config_id"] == PLACEHOLDER_CONFIG
    assert _rule_values(request["output_json"]) == {
        "quality.delivered": 1.0,
        "quality.merged": 1.0,
        "quality.ci_first_pass": 0.0,
        "quality.no_review_fixes_needed": 1.0,
        "ux.autonomy": 1.0,
    }


async def test_status_of_pending_observed_run_is_not_executable(db_session, client_as) -> None:
    """An observed run never carries an execute_run job, so the runner can never pick it up."""
    editor = await client_as(Role.editor)
    scenario = await create_nova_scenario(editor)
    av = await create_agent_version(db_session)
    await db_session.commit()
    run_id = uuid.UUID((await editor.post(URL, json=observed_body(av.id, scenario["id"]))).json()["id"])
    kinds = [j.kind for j in await db_session.scalars(select(Job).where(Job.run_id == run_id))]
    assert JobKind.execute_run not in kinds
    row = await db_session.get(EvaluationRun, run_id)
    assert row.status == RunStatus.evaluating and row.queued_at is None and row.executed_at is not None
