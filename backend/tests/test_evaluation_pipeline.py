"""Evaluation engine: full pipeline on executed runs (rules, metrics, heuristic judge, scores, errors)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from forge.domain.enums import EvaluatorKind, RunStatus, ScoreSource
from forge.infra.models import AuditEvent, CompositeScore, Evaluation, FeedbackReport, RunError, Score
from forge.services import runs as run_service
from tests.conftest import run_jobs
from tests.factories import attach_trace, create_agent_version, create_run, create_scenario_version

PRD = """# PRD — Export CSV

## Objectifs
Permettre l'export CSV des rapports, car les clients le demandent [doc-1].

## Périmètre
Export des rapports mensuels.

## Exigences
- Export en moins de 5 secondes
- Encodage UTF-8

## Critères d'acceptation
- Le fichier s'ouvre dans un tableur.
"""


async def _executed_run(db_session, *, output=PRD, rules=None, events=None, **scenario):
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(
        db_session,
        rules=rules
        if rules is not None
        else [
            {
                "id": "sections",
                "type": "sections_present",
                "params": {"sections": ["Objectifs", "Périmètre"]},
            },
            {"id": "no-email", "type": "no_pii", "severity": "high"},
        ],
        context={
            "documents": [
                {"id": "doc-1", "title": "Demandes clients", "content": "Les clients veulent un export CSV."}
            ]
        },
        **scenario,
    )
    run = await create_run(db_session, sv, av)
    await attach_trace(db_session, run, output_text=output, events=events)
    await run_service.mark_evaluating(db_session, run)
    await db_session.commit()
    return run


async def test_pipeline_scores_run(db_session) -> None:
    run = await _executed_run(db_session)
    assert await run_jobs() >= 1
    await db_session.refresh(run)
    assert run.status == RunStatus.completed, run.status_detail
    assert run.evaluation_round == 1
    assert run.composite_score is not None and 0 <= run.composite_score <= 100
    evaluations = list(await db_session.scalars(select(Evaluation).where(Evaluation.run_id == run.id)))
    kinds = {e.evaluator_kind for e in evaluations}
    assert {EvaluatorKind.rule, EvaluatorKind.metric, EvaluatorKind.llm_judge} <= kinds
    assert all(e.explanation.strip() for e in evaluations)
    judge_rows = [e for e in evaluations if e.evaluator_kind == EvaluatorKind.llm_judge]
    assert judge_rows[0].prompt_hash and judge_rows[0].prompt_hash.startswith("sha256:")
    assert any("prompt" in (e.raw_response or {}) for e in judge_rows)
    scores = list(await db_session.scalars(select(Score).where(Score.run_id == run.id)))
    assert {s.source for s in scores} >= {ScoreSource.rule, ScoreSource.metric, ScoreSource.ai}
    composite = await db_session.scalar(select(CompositeScore).where(CompositeScore.run_id == run.id))
    assert composite is not None and composite.formula
    feedback = await db_session.scalar(select(FeedbackReport).where(FeedbackReport.run_id == run.id))
    assert feedback is not None and feedback.summary
    audit_row = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "run.evaluate", AuditEvent.target_id == str(run.id))
    )
    assert audit_row is not None


async def test_pii_triggers_data_leak_gate(db_session) -> None:
    run = await _executed_run(db_session, output=PRD + "\nContact : jean.dupont@example.com\n")
    await run_jobs()
    await db_session.refresh(run)
    errors = list(await db_session.scalars(select(RunError).where(RunError.run_id == run.id)))
    assert any(e.error_type == "DATA_LEAK" for e in errors)
    assert run.gate_failed is True
    assert run.composite_score == 0
    assert run.passed is False


async def test_failed_execution_scores_zero_and_records_error(db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(
        db_session, rules=[{"id": "R1", "type": "contains", "params": {"keywords": ["PRD"]}}]
    )
    run = await create_run(db_session, sv, av)
    await attach_trace(db_session, run, output_text="")
    run.error, run.error_type = "Agent injoignable (HTTP 502)", "EXECUTION_ERROR"
    await run_service.mark_evaluating(db_session, run)
    await db_session.commit()
    await run_jobs()
    await db_session.refresh(run)
    assert run.status == RunStatus.failed
    assert run.composite_score == 0 and run.passed is False
    errors = list(await db_session.scalars(select(RunError).where(RunError.run_id == run.id)))
    execution = [e for e in errors if e.round is None]
    assert len(execution) == 1 and execution[0].error_type == "EXECUTION_ERROR"
    kinds = {
        e.evaluator_kind
        for e in await db_session.scalars(select(Evaluation).where(Evaluation.run_id == run.id))
    }
    assert EvaluatorKind.llm_judge not in kinds and EvaluatorKind.rule in kinds
    composite = await db_session.scalar(select(CompositeScore).where(CompositeScore.run_id == run.id))
    assert "exécution de l'agent en échec" in composite.formula


async def test_errors_are_deduplicated_and_linked_to_trace(db_session) -> None:
    rules = [
        {"id": "pii-a", "type": "no_pii", "severity": "medium"},
        {"id": "pii-b", "type": "no_pii", "severity": "medium"},
        {"id": "no-mail", "type": "tool_not_called", "params": {"tool": "send_email"}},
    ]
    events = [{"type": "tool_call", "name": "send_email", "attributes": {"tool": "send_email"}}]
    run = await _executed_run(db_session, output=PRD + "\nmarie@example.org", rules=rules, events=events)
    await run_jobs()
    errors = list(await db_session.scalars(select(RunError).where(RunError.run_id == run.id)))
    leaks = [e for e in errors if e.error_type == "DATA_LEAK"]
    assert len(leaks) == 1 and "détectée par" in leaks[0].description
    assert "rule:pii-a" in leaks[0].description and "rule:pii-b" in leaks[0].description
    wrong_tool = next(e for e in errors if e.error_type == "WRONG_TOOL")
    assert wrong_tool.trace_event_id is not None and wrong_tool.evaluation_id is not None


async def test_rescore_after_human_evaluation(db_session) -> None:
    from forge.domain.enums import Dimension
    from forge.services import evaluation as evaluation_service
    from tests.factories import default_config

    config = await default_config(db_session)
    run = await _executed_run(db_session)
    await run_jobs()
    await db_session.refresh(run)
    before = run.composite_score
    db_session.add(
        Evaluation(
            run_id=run.id, round=None, evaluation_config_id=config.id, evaluator_kind=EvaluatorKind.human,
            evaluator_key="human:test", criterion_key="quality.accuracy", dimension=Dimension.quality,
            raw_score=0, scale_min=0, scale_max=5, normalized_score=0, confidence=1,
            explanation="Réponse inexacte selon l'expert.",
        )
    )  # fmt: skip
    await db_session.flush()
    result = await evaluation_service.rescore_run(db_session, run)
    await db_session.commit()
    assert result is not None and result.round == 1
    scores = list(
        await db_session.scalars(
            select(Score).where(Score.run_id == run.id, Score.criterion_key == "quality.accuracy")
        )
    )
    human = next(s for s in scores if s.source == ScoreSource.human)
    assert human.used_in_composite is False  # forge-default does not use human scores
    assert run.composite_score == pytest.approx(before)
    spec_config = evaluation_service.specs_from_manifest(run.manifest).config
    spec_config.use_human_scores = True
    preview = await evaluation_service.rescore_run(db_session, run, config=spec_config, persist=False)
    assert preview.composite.raw_value < result.composite.raw_value
    feedback_count = len(
        list(await db_session.scalars(select(FeedbackReport).where(FeedbackReport.run_id == run.id)))
    )
    assert feedback_count == 1  # regenerated, not duplicated


async def test_reevaluation_creates_new_round(db_session) -> None:
    from forge.services import evaluation as evaluation_service

    run = await _executed_run(db_session)
    await run_jobs()
    await db_session.refresh(run)
    job = await evaluation_service.start_reevaluation(db_session, run)
    await db_session.commit()
    assert job is not None and run.status == RunStatus.evaluating
    with pytest.raises(evaluation_service.EvaluationStateError):
        await evaluation_service.start_reevaluation(db_session, run)
    await run_jobs()
    await db_session.refresh(run)
    assert run.status == RunStatus.completed and run.evaluation_round == 2
    rounds = await evaluation_service.evaluation_rounds(db_session, run.id)
    assert rounds == [1, 2]
