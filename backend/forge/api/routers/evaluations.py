"""Router ``evaluations`` (docs §12): re-evaluation, verdicts, scores, errors, feedback, provenance.

Access: runs above the caller's clearance are not revealed (404). For private scenarios, callers
below maintainer see results (scores, error types, severities, costs) but not justifications,
evidence, rule parameters nor prompts (``forge.domain.redaction``); hidden rules are masked on every
scenario. Reads: viewer; re-evaluation: editor.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query, status

from forge.api.deps import Principal, RequireEditor, RequireViewer, SessionDep
from forge.api.errors import conflict, not_found
from forge.api.schemas.evaluations import (
    CompositeOut,
    EvaluateIn,
    EvaluateOut,
    EvaluationOut,
    FeedbackReportOut,
    ProvenanceAggregation,
    ProvenanceComposite,
    ProvenanceCriterion,
    ProvenanceEvaluator,
    ProvenanceEvent,
    ProvenanceJudge,
    ProvenanceOut,
    ProvenancePrompt,
    ProvenanceRule,
    RunErrorOut,
    RunErrorsOut,
    RunEvaluationsOut,
    RunScoresOut,
    ScoreOut,
)
from forge.domain.enums import EvaluatorKind, ScoreSource
from forge.domain.redaction import (
    REDACTED_JUSTIFICATION,
    redact_error,
    redact_evaluation,
    redact_rule,
)
from forge.domain.types import to_dict
from forge.infra.models import EvaluationConfig, EvaluationRun, FeedbackReport, RunError, Scenario, Score
from forge.services import evaluation as evaluation_service
from forge.services import feedback as feedback_service
from forge.services.access import can_view_scenario, must_redact
from forge.services.mapping import load_criteria_catalog, specs_from_manifest

router = APIRouter(tags=["evaluations"])


class _Access:
    """Redaction policy of one run for one caller."""

    def __init__(self, principal: Principal, run: EvaluationRun, scenario: Scenario) -> None:
        manifest_visibility = str((run.manifest.get("scenario") or {}).get("visibility") or "public")
        self.private = must_redact(principal, manifest_visibility) or must_redact(
            principal, scenario.visibility
        )
        self.maintainer = principal.can_see_private
        specs = specs_from_manifest(run.manifest)
        self.hidden_rules = (
            set()
            if self.maintainer
            else {r.id for r in [*specs.scenario.rules, *specs.config.rules] if r.hidden}
        )

    def hidden_rule(self, kind: EvaluatorKind | None, key: str) -> bool:
        return kind == EvaluatorKind.rule and key.split("#", 1)[0] in self.hidden_rules

    def redact_evaluation(self, row: Any) -> bool:
        kind = EvaluatorKind(row.evaluator_kind)
        return (self.private and kind != EvaluatorKind.metric) or self.hidden_rule(kind, row.evaluator_key)


async def _visible_run(
    session: SessionDep, run_id: uuid.UUID, principal: Principal
) -> tuple[EvaluationRun, Scenario]:
    found = await evaluation_service.get_run_for_viewer(session, run_id, principal)
    if found is None:
        raise not_found("Run introuvable")
    return found


def _evaluation_out(row: Any, access: _Access) -> EvaluationOut:
    data = EvaluationOut.model_validate(row, from_attributes=True).model_dump()
    if access.redact_evaluation(row):
        data = redact_evaluation(data)
        data.pop("raw_response", None)
    return EvaluationOut.model_validate(data)


def _score_out(row: Score, access: _Access, names: dict[str, str], hidden_scores: set[uuid.UUID]) -> ScoreOut:
    redacted = (access.private and row.source != ScoreSource.metric) or row.id in hidden_scores
    return ScoreOut(
        id=row.id,
        round=row.round,
        evaluation_config_id=row.evaluation_config_id,
        criterion_key=row.criterion_key,
        criterion_name=names.get(row.criterion_key),
        dimension=row.dimension,
        value=row.value,
        weight=row.weight,
        source=row.source,
        confidence=row.confidence,
        explanation=REDACTED_JUSTIFICATION if redacted else row.explanation,
        method=row.method,
        n_evaluations=row.n_evaluations,
        spread=row.spread,
        evaluation_ids=list(row.evaluation_ids or []),
        used_in_composite=row.used_in_composite,
        redacted=redacted,
    )


def _error_out(
    row: RunError, access: _Access, labels: dict[str, str], seqs: dict[uuid.UUID, Any]
) -> RunErrorOut:
    event = seqs.get(row.trace_event_id) if row.trace_event_id else None
    data = {
        "id": row.id, "round": row.round, "error_type": row.error_type,
        "label": labels.get(row.error_type, row.error_type), "severity": row.severity,
        "description": row.description, "evidence": list(row.evidence or []),
        "evaluator_kind": row.evaluator_kind, "evaluator_key": row.evaluator_key,
        "evaluation_id": row.evaluation_id, "trace_event_id": row.trace_event_id,
        "trace_event_seq": event.seq if event is not None else None, "criterion_key": row.criterion_key,
        "created_at": row.created_at,
    }  # fmt: skip
    if access.private or access.hidden_rule(row.evaluator_kind, row.evaluator_key):
        data = redact_error(data)
    return RunErrorOut.model_validate(data)


def _composite_out(row: Any) -> CompositeOut:
    return CompositeOut.model_validate(row, from_attributes=True)


def _report_out(row: FeedbackReport, *, redact: bool) -> FeedbackReportOut:
    data = feedback_service.report_data(row)
    if redact:
        data = feedback_service.redact_report(data)
    data["created_at"] = row.created_at
    return FeedbackReportOut.model_validate(data)


async def _hidden_score_ids(scores: list[Score], access: _Access, session: SessionDep) -> set[uuid.UUID]:
    if not access.hidden_rules:
        return set()
    hidden: set[uuid.UUID] = set()
    rule_scores = [s for s in scores if s.source == ScoreSource.rule]
    if not rule_scores:
        return hidden
    ids = [uuid.UUID(i) for s in rule_scores for i in s.evaluation_ids or []]
    rows = await evaluation_service.round_evaluations(session, scores[0].run_id, scores[0].round)
    hidden_evals = {
        r.id for r in rows if r.id in set(ids) and access.hidden_rule(r.evaluator_kind, r.evaluator_key)
    }
    for score in rule_scores:
        if any(uuid.UUID(i) in hidden_evals for i in score.evaluation_ids or []):
            hidden.add(score.id)
    return hidden


# --- Endpoints -------------------------------------------------------------------------------------


@router.post(
    "/runs/{run_id}/evaluate",
    response_model=EvaluateOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ré-évaluer un run (nouveau round, éventuellement avec une autre configuration)",
)
async def evaluate_run(
    run_id: uuid.UUID, principal: RequireEditor, session: SessionDep, body: EvaluateIn | None = None
) -> EvaluateOut:
    run, _scenario = await _visible_run(session, run_id, principal)
    config: EvaluationConfig | None = None
    if body is not None and body.evaluation_config_id is not None:
        config = await session.get(EvaluationConfig, body.evaluation_config_id)
        if config is None:
            raise not_found("Configuration d'évaluation introuvable")
    try:
        job = await evaluation_service.start_reevaluation(session, run, config=config, actor=principal)
    except evaluation_service.EvaluationStateError as exc:
        raise conflict(str(exc)) from exc
    await session.commit()
    return EvaluateOut(
        run_id=run.id,
        status=run.status,
        next_round=run.evaluation_round + 1,
        job_id=job.id if job is not None else None,
        evaluation_config_id=config.id if config is not None else run.evaluation_config_id,
    )


@router.get(
    "/runs/{run_id}/evaluations", response_model=RunEvaluationsOut, summary="Verdicts individuels d'un run"
)
async def list_evaluations(
    run_id: uuid.UUID,
    principal: RequireViewer,
    session: SessionDep,
    round: int | None = Query(default=None, ge=1, description="Round (défaut : le plus récent)"),
    kind: EvaluatorKind | None = None,
    criterion_key: str | None = None,
) -> RunEvaluationsOut:
    run, scenario = await _visible_run(session, run_id, principal)
    access = _Access(principal, run, scenario)
    round_no = evaluation_service.resolve_round(run, round)
    rows = (
        await evaluation_service.round_evaluations(
            session, run.id, round_no, kind=kind, criterion_key=criterion_key
        )
        if round_no is not None
        else await evaluation_service.round_evaluations(
            session, run.id, None, kind=kind, criterion_key=criterion_key
        )
    )
    return RunEvaluationsOut(
        run_id=run.id,
        round=round_no,
        rounds=await evaluation_service.evaluation_rounds(session, run.id),
        items=[_evaluation_out(r, access) for r in rows],
    )


@router.get("/runs/{run_id}/scores", response_model=RunScoresOut, summary="Scores par critère et composite")
async def get_scores(
    run_id: uuid.UUID,
    principal: RequireViewer,
    session: SessionDep,
    round: int | None = Query(default=None, ge=1),
) -> RunScoresOut:
    run, scenario = await _visible_run(session, run_id, principal)
    access = _Access(principal, run, scenario)
    round_no = evaluation_service.resolve_round(run, round)
    composite = await evaluation_service.round_composite(session, run.id, round_no)
    config_id = composite.evaluation_config_id if composite else None
    scores = await evaluation_service.round_scores(session, run.id, round_no, config_id)
    catalog = await load_criteria_catalog(session)
    names = {k: c.name for k, c in catalog.items()}
    hidden = await _hidden_score_ids(scores, access, session)
    return RunScoresOut(
        run_id=run.id,
        round=round_no,
        rounds=await evaluation_service.evaluation_rounds(session, run.id),
        status=run.status,
        evaluation_config_id=config_id,
        composite=_composite_out(composite) if composite else None,
        scores=[_score_out(s, access, names, hidden) for s in scores],
        status_detail=run.status_detail,
    )


@router.get("/runs/{run_id}/errors", response_model=RunErrorsOut, summary="Erreurs classées d'un run")
async def list_errors(
    run_id: uuid.UUID,
    principal: RequireViewer,
    session: SessionDep,
    round: int | None = Query(default=None, ge=1),
) -> RunErrorsOut:
    run, scenario = await _visible_run(session, run_id, principal)
    access = _Access(principal, run, scenario)
    round_no = evaluation_service.resolve_round(run, round)
    rows = await evaluation_service.round_errors(session, run.id, round_no)
    labels = await evaluation_service.error_type_labels(session)
    events = await evaluation_service.event_seqs(
        session, [r.trace_event_id for r in rows if r.trace_event_id]
    )
    return RunErrorsOut(
        run_id=run.id, round=round_no, items=[_error_out(r, access, labels, events) for r in rows]
    )


@router.get(
    "/runs/{run_id}/feedback", response_model=FeedbackReportOut, summary="Rapport de feedback d'un run"
)
async def get_run_feedback(
    run_id: uuid.UUID,
    principal: RequireViewer,
    session: SessionDep,
    round: int | None = Query(default=None, ge=1),
) -> FeedbackReportOut:
    run, scenario = await _visible_run(session, run_id, principal)
    access = _Access(principal, run, scenario)
    report = await feedback_service.latest_run_feedback(session, run.id, round)
    if report is None:
        raise not_found("Aucun rapport de feedback pour ce run")
    return _report_out(report, redact=access.private or bool(access.hidden_rules))


@router.get("/feedback-reports/{report_id}", response_model=FeedbackReportOut, summary="Rapport de feedback")
async def get_feedback_report(
    report_id: uuid.UUID, principal: RequireViewer, session: SessionDep
) -> FeedbackReportOut:
    report = await session.get(FeedbackReport, report_id)
    if report is None:
        raise not_found("Rapport de feedback introuvable")
    redact = False
    if report.run_id is not None:
        run = await session.get(EvaluationRun, report.run_id)
        scenario = await session.get(Scenario, run.scenario_id) if run else None
        if run is None or scenario is None or not can_view_scenario(principal, scenario):
            raise not_found("Rapport de feedback introuvable")
        access = _Access(principal, run, scenario)
        redact = access.private or bool(access.hidden_rules)
    return _report_out(report, redact=redact)


@router.get(
    "/runs/{run_id}/scores/{criterion_key}/provenance",
    response_model=ProvenanceOut,
    summary="Provenance d'un score : évaluateurs, juges, prompts, règles, preuves, agrégation",
)
async def get_provenance(
    run_id: uuid.UUID,
    criterion_key: str,
    principal: RequireViewer,
    session: SessionDep,
    round: int | None = Query(default=None, ge=1),
) -> ProvenanceOut:
    run, scenario = await _visible_run(session, run_id, principal)
    access = _Access(principal, run, scenario)
    prov = await evaluation_service.score_provenance(session, run, criterion_key, round)
    if prov is None:
        raise not_found(f"Aucun score pour le critère « {criterion_key} »")
    hidden_scores = await _hidden_score_ids(prov.scores, access, session)
    names = {criterion_key: prov.criterion.name}
    scores_out = [_score_out(s, access, names, hidden_scores) for s in prov.scores]
    by_id = {e.id: e for e in prov.evaluations}
    evaluators: list[ProvenanceEvaluator] = []
    for row in prov.evaluations:
        out = _evaluation_out(row, access)
        raw = row.raw_response if isinstance(row.raw_response, dict) else {}
        judge_out = rule_out = metric = prompt_out = None
        if row.evaluator_kind == EvaluatorKind.llm_judge:
            spec = prov.judges.get(row.evaluator_key)
            judge_out = ProvenanceJudge(
                id=row.judge_id,
                key=spec.key if spec else row.evaluator_key.split("@")[0],
                version=row.judge_version,
                name=spec.name if spec else None,
                provider=spec.provider if spec else None,
                model=row.model or (spec.model if spec else None),
                weight=spec.weight if spec else None,
                content_hash=spec.content_hash if spec else None,
            )
            prompt_ref = row.id if row.id in prov.prompts else None
            if prompt_ref is None:
                ref = raw.get("prompt_evaluation_id")
                prompt_ref = uuid.UUID(ref) if ref and uuid.UUID(ref) in prov.prompts else None
            stored = prov.prompts.get(prompt_ref) if prompt_ref else None
            visible = access.maintainer and stored is not None
            prompt_out = ProvenancePrompt(
                prompt_hash=row.prompt_hash,
                system=stored.get("system") if visible and stored else None,
                user=stored.get("user") if visible and stored else None,
                available=stored is not None,
            )
        elif row.evaluator_kind == EvaluatorKind.rule:
            base_id = row.evaluator_key.split("#", 1)[0]
            rule_entry = prov.rules.get(base_id)
            if rule_entry is not None:
                rule, source = rule_entry
                rule_data = to_dict(rule)
                masked = access.private or (rule.hidden and not access.maintainer)
                if masked:
                    rule_data = redact_rule(rule_data)
                rule_out = ProvenanceRule(
                    id=rule.id,
                    type=str(rule_data.get("type")),
                    description=str(rule_data.get("description") or ""),
                    params=dict(rule_data.get("params") or {}),
                    weight=rule.weight,
                    severity=str(rule_data.get("severity") or ""),
                    hidden=bool(rule.hidden),
                    source=source,
                    redacted=masked,
                )
        elif row.evaluator_kind == EvaluatorKind.metric:
            metric = {k: raw.get(k) for k in ("value", "target", "max")}
        seqs = sorted(
            {
                int(ref["trace_event_seq"])
                for ref in row.evidence or []
                if ref.get("trace_event_seq") is not None
            }
        )
        events = [
            ProvenanceEvent(
                seq=seq,
                id=prov.events[seq].id if seq in prov.events else None,
                type=prov.events[seq].type.value if seq in prov.events else None,
                name=prov.events[seq].name if seq in prov.events else None,
            )
            for seq in seqs
        ]
        evaluators.append(
            ProvenanceEvaluator(
                evaluation=out,
                judge=judge_out,
                rule=rule_out,
                metric=metric,
                trace_events=events,
                prompt=prompt_out,
            )
        )
    aggregations: list[ProvenanceAggregation] = []
    for score in prov.scores:
        verdicts = []
        for raw_id in score.evaluation_ids or []:
            verdict_row = by_id.get(uuid.UUID(raw_id))
            if verdict_row is None:
                continue
            verdicts.append(
                {
                    "evaluation_id": str(verdict_row.id),
                    "evaluator_kind": verdict_row.evaluator_kind.value,
                    "evaluator_key": verdict_row.evaluator_key,
                    "raw_score": verdict_row.raw_score,
                    "normalized_score": verdict_row.normalized_score,
                    "confidence": verdict_row.confidence,
                }
            )
        agg = prov.config.aggregation
        redacted = (access.private and score.source != ScoreSource.metric) or score.id in hidden_scores
        aggregations.append(
            ProvenanceAggregation(
                source=score.source,
                method=score.method,
                configured_method=agg.method.value if score.source == ScoreSource.ai else score.source.value,
                weights=dict(agg.weights or {}) if score.source == ScoreSource.ai else {},
                expression=agg.expression if score.source == ScoreSource.ai else None,
                value=score.value,
                confidence=score.confidence,
                spread=score.spread,
                explanation=REDACTED_JUSTIFICATION if redacted else score.explanation,
                individual_verdicts=verdicts,
            )
        )
    composite_out = None
    if prov.composite is not None:
        dimension = prov.criterion.dimension
        dim = next(
            (d for d in prov.composite.dimensions or [] if d.get("dimension") == dimension.value), None
        )
        used = any(s.used_in_composite for s in prov.scores)
        composite_out = ProvenanceComposite(
            used_in_composite=used,
            dimension=dimension,
            dimension_value=dim.get("value") if dim else None,
            dimension_weight=dim.get("weight") if dim else None,
            effective_weight=dim.get("effective_weight") if dim else None,
            criterion_weight=max((s.weight for s in prov.scores), default=prov.criterion.weight),
            composite=prov.composite.value,
            formula=prov.composite.formula,
        )
    labels = await evaluation_service.error_type_labels(session)
    events_by_id = {e.id: e for e in prov.events.values()}
    criterion = prov.criterion
    return ProvenanceOut(
        run_id=run.id,
        round=prov.round,
        criterion=ProvenanceCriterion(
            key=criterion.key,
            name=criterion.name,
            dimension=criterion.dimension,
            question=criterion.question,
            rubric=criterion.rubric,
            scale_min=criterion.scale_min,
            scale_max=criterion.scale_max,
            weight=criterion.weight,
        ),
        evaluation_config={
            "id": str(prov.config_id),
            "key": prov.config.key,
            "version": prov.config.version,
            "aggregation": to_dict(prov.config.aggregation),
            "use_human_scores": prov.config.use_human_scores,
        },
        scores=scores_out,
        aggregations=aggregations,
        evaluators=evaluators,
        composite=composite_out,
        errors=[_error_out(e, access, labels, events_by_id) for e in prov.errors],
        redacted=access.private,
        prompts_visible=access.maintainer,
    )
