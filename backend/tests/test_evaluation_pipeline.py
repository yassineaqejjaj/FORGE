"""Evaluation engine: full pipeline on executed runs (rules, metrics, heuristic judge, scores, errors)."""

from __future__ import annotations

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
            {"id": "sections", "type": "sections_present", "params": {"sections": ["Objectifs", "Périmètre"]}},
            {"id": "no-email", "type": "no_pii", "severity": "high"},
        ],
        context={"documents": [{"id": "doc-1", "title": "Demandes clients", "content": "Les clients veulent un export CSV."}]},
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
