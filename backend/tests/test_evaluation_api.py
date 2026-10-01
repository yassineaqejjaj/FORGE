"""Evaluation API (docs §12): verdicts, scores, errors, feedback, provenance, re-evaluation, access."""

from __future__ import annotations

from sqlalchemy import select

from forge.domain.enums import Role, ScenarioVisibility
from forge.domain.redaction import REDACTED_JUSTIFICATION
from forge.infra.models import FeedbackReport, Scenario
from forge.services import runs as run_service
from tests.conftest import run_jobs
from tests.factories import attach_trace, create_agent_version, create_run, create_scenario_version

OUTPUT = "# Objectifs\nExport CSV [doc-1].\n## Périmètre\nRapports mensuels.\nContact : paul@example.com"
RULES = [
    {"id": "sections", "type": "sections_present", "params": {"sections": ["Objectifs", "Périmètre"]}},
    {"id": "secret-rule", "type": "contains", "params": {"keywords": ["mot-secret"]}, "hidden": True},
    {"id": "no-pii", "type": "no_pii", "severity": "medium"},
]


async def _evaluated_run(db_session, *, visibility=ScenarioVisibility.public, classification: int = 1):
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(
        db_session,
        visibility=visibility,
        rules=RULES,
        expected_output="Objectifs export CSV périmètre rapports mensuels",
        context={"documents": [{"id": "doc-1", "title": "Demandes clients"}]},
    )
    scenario = await db_session.get(Scenario, sv.scenario_id)
    scenario.classification = classification
    run = await create_run(db_session, sv, av)
    await attach_trace(
        db_session,
        run,
        output_text=OUTPUT,
        events=[{"type": "tool_call", "name": "search_docs", "attributes": {"tool": "search_docs"}}],
    )
    await run_service.mark_evaluating(db_session, run)
    await db_session.commit()
    await run_jobs()
    await db_session.refresh(run)
    return run


async def test_scores_evaluations_errors_feedback(db_session, client_as) -> None:
    run = await _evaluated_run(db_session)
    viewer = await client_as(Role.viewer)
    scores = (await viewer.get(f"/api/v1/runs/{run.id}/scores")).json()
    assert scores["round"] == 1 and scores["rounds"] == [1]
    assert scores["composite"]["formula"] and scores["composite"]["value"] == run.composite_score
    assert {s["source"] for s in scores["scores"]} >= {"rule", "metric", "ai"}
    evaluations = (await viewer.get(f"/api/v1/runs/{run.id}/evaluations")).json()
    by_key = {e["evaluator_key"]: e for e in evaluations["items"]}
    assert by_key["sections"]["redacted"] is False
    assert by_key["secret-rule"]["redacted"] is True  # hidden rules masked on every scenario
    assert by_key["secret-rule"]["explanation"] == REDACTED_JUSTIFICATION
    only_rules = (await viewer.get(f"/api/v1/runs/{run.id}/evaluations", params={"kind": "rule"})).json()
    assert {e["evaluator_kind"] for e in only_rules["items"]} == {"rule"}
    errors = (await viewer.get(f"/api/v1/runs/{run.id}/errors")).json()["items"]
    leak = next(e for e in errors if e["error_type"] == "DATA_LEAK")
    assert leak["label"] == "Fuite de données" and leak["redacted"] is False
    hidden_error = next(e for e in errors if e["evaluator_key"] == "secret-rule")
    assert hidden_error["redacted"] is True
    feedback = await viewer.get(f"/api/v1/runs/{run.id}/feedback")
    assert feedback.status_code == 200 and feedback.json()["scope"] == "run"
    report_id = feedback.json()["id"]
    assert (await viewer.get(f"/api/v1/feedback-reports/{report_id}")).status_code == 200
    maintainer = await client_as(Role.maintainer)
    full = (await maintainer.get(f"/api/v1/runs/{run.id}/evaluations")).json()
    assert {e["evaluator_key"]: e for e in full["items"]}["secret-rule"]["redacted"] is False


async def test_provenance_answers_audit_questions(db_session, client_as) -> None:
    run = await _evaluated_run(db_session)
    maintainer = await client_as(Role.maintainer)
    response = await maintainer.get(f"/api/v1/runs/{run.id}/scores/quality.accuracy/provenance")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["criterion"]["key"] == "quality.accuracy" and data["round"] == 1
    judge_eval = next(e for e in data["evaluators"] if e["evaluation"]["evaluator_kind"] == "llm_judge")
    assert judge_eval["judge"]["key"] == "forge-heuristic" and judge_eval["judge"]["version"] == 1
    assert judge_eval["prompt"]["prompt_hash"].startswith("sha256:")
    assert judge_eval["prompt"]["available"] and "Critères à évaluer" in judge_eval["prompt"]["user"]
    assert judge_eval["evaluation"]["explanation"] and judge_eval["evaluation"]["confidence"] <= 0.6
    agg = next(a for a in data["aggregations"] if a["source"] == "ai")
    assert agg["configured_method"] == "median" and agg["individual_verdicts"]
    assert data["composite"]["used_in_composite"] is True and data["composite"]["formula"]

    rule_prov = (await maintainer.get(f"/api/v1/runs/{run.id}/scores/quality.format/provenance")).json()
    rule_eval = next(e for e in rule_prov["evaluators"] if e["evaluation"]["evaluator_key"] == "sections")
    assert rule_eval["rule"]["type"] == "sections_present"
    assert rule_eval["rule"]["params"] == {"sections": ["Objectifs", "Périmètre"]}

    viewer = await client_as(Role.viewer)
    viewer_view = (await viewer.get(f"/api/v1/runs/{run.id}/scores/quality.accuracy/provenance")).json()
    judge_view = next(
        e for e in viewer_view["evaluators"] if e["evaluation"]["evaluator_kind"] == "llm_judge"
    )
    assert (
        judge_view["prompt"]["user"] is None and judge_view["prompt"]["prompt_hash"]
    )  # prompt: maintainers only
    hidden = (await viewer.get(f"/api/v1/runs/{run.id}/scores/coherence.constraints/provenance")).json()
    hidden_rule = next(e for e in hidden["evaluators"] if e["evaluation"]["evaluator_key"] == "secret-rule")
    assert hidden_rule["rule"]["redacted"] is True and hidden_rule["rule"]["params"] == {}
    missing = await viewer.get(f"/api/v1/runs/{run.id}/scores/nope.nope/provenance")
    assert missing.status_code == 404


async def test_private_scenario_redaction(db_session, client_as) -> None:
    run = await _evaluated_run(db_session, visibility=ScenarioVisibility.private)
    viewer = await client_as(Role.viewer)
    scores = (await viewer.get(f"/api/v1/runs/{run.id}/scores")).json()
    assert scores["composite"]["value"] == run.composite_score  # results stay visible
    ai = [s for s in scores["scores"] if s["source"] == "ai"]
    assert ai and all(s["redacted"] and s["explanation"] == REDACTED_JUSTIFICATION for s in ai)
    metrics = [s for s in scores["scores"] if s["source"] == "metric"]
    assert metrics and not any(s["redacted"] for s in metrics)
    evaluations = (await viewer.get(f"/api/v1/runs/{run.id}/evaluations")).json()["items"]
    judged = [e for e in evaluations if e["evaluator_kind"] == "llm_judge"]
    assert all(e["evidence"] == [] and e["redacted"] for e in judged)
    errors = (await viewer.get(f"/api/v1/runs/{run.id}/errors")).json()["items"]
    assert errors and all(e["redacted"] and e["evidence"] == [] for e in errors)
    assert {e["error_type"] for e in errors}  # types and severities stay visible
    feedback = (await viewer.get(f"/api/v1/runs/{run.id}/feedback")).json()
    assert feedback["redacted"] is True
    maintainer = await client_as(Role.maintainer)
    full = (await maintainer.get(f"/api/v1/runs/{run.id}/evaluations")).json()["items"]
    assert not any(e["redacted"] for e in full)


async def test_runs_above_clearance_are_hidden(db_session, client_as) -> None:
    run = await _evaluated_run(db_session, classification=3)
    low = await client_as(Role.viewer, clearance=1)
    for path in ("scores", "evaluations", "errors", "feedback", "scores/quality.accuracy/provenance"):
        assert (await low.get(f"/api/v1/runs/{run.id}/{path}")).status_code == 404, path
    report = await db_session.scalar(select(FeedbackReport).where(FeedbackReport.run_id == run.id))
    assert (await low.get(f"/api/v1/feedback-reports/{report.id}")).status_code == 404
    high = await client_as(Role.viewer, clearance=3)
    assert (await high.get(f"/api/v1/runs/{run.id}/scores")).status_code == 200


async def test_reevaluate_endpoint(db_session, client_as) -> None:
    run = await _evaluated_run(db_session)
    viewer = await client_as(Role.viewer)
    assert (await viewer.post(f"/api/v1/runs/{run.id}/evaluate", json={})).status_code == 403
    editor = await client_as(Role.editor)
    response = await editor.post(f"/api/v1/runs/{run.id}/evaluate", json={})
    assert response.status_code == 202, response.text
    assert response.json()["next_round"] == 2 and response.json()["status"] == "evaluating"
    assert (await editor.post(f"/api/v1/runs/{run.id}/evaluate")).status_code == 409  # already evaluating
    await run_jobs()
    scores = (await viewer.get(f"/api/v1/runs/{run.id}/scores")).json()
    assert scores["round"] == 2 and scores["rounds"] == [1, 2]
    first = (await viewer.get(f"/api/v1/runs/{run.id}/scores", params={"round": 1})).json()
    assert first["round"] == 1 and first["composite"] is not None
    unknown = await editor.post(
        f"/api/v1/runs/{run.id}/evaluate",
        json={"evaluation_config_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert unknown.status_code == 404
    missing = await editor.post("/api/v1/runs/00000000-0000-0000-0000-000000000000/evaluate", json={})
    assert missing.status_code == 404
