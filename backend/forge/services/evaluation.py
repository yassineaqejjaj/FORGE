"""Evaluation Engine service (docs/ARCHITECTURE.md §7.1): ``evaluate_run`` job, rescoring, re-evaluation.

Pipeline of :func:`evaluate_run_job` (queue ``evaluation``):

1. load the run, its trace and events (``TraceEventView``, stable ``seq``) and the **manifest** specs;
2. ``round = run.evaluation_round + 1``;
3. deterministic evaluators of ``forge.domain.evaluators_registry`` (scenario + configuration rules,
   cost / tokens / latency metrics);
4. judges of the configuration in parallel (``cache.throttle`` per credential), with the
   ``judge_cache`` table; skipped when the execution failed;
5. persistence of every verdict (``evaluations``), per-criterion ``scores``, ``composite_scores``,
   de-duplicated ``run_errors`` (``trace_event_id`` resolved from ``seq``) and the run
   ``feedback_reports``; run denormalisation, audit ``run.evaluate``, metrics;
6. ``runs.mark_completed`` — or ``runs.mark_failed`` with composite 0 when the execution failed.

Services only flush; the worker commits. :func:`rescore_run` recomputes scores from stored verdicts
(no judge call) after human evaluations or for configuration previews.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import (
    SEVERITY_RANK,
    BuiltinErrorType,
    ErrorSeverity,
    EvaluatorKind,
    JobKind,
    JudgeProvider,
    RunStatus,
)
from forge.domain.evaluators_registry import deterministic_evaluators, validate_results
from forge.domain.feedback import FeedbackCriterion, FeedbackError, FeedbackInput
from forge.domain.judges import (
    JudgeRun,
    cache_payload,
    criteria_for_judge,
    judge_cache_key,
    judged_criteria,
    parse_stored_response,
    render_prompt,
    run_judge,
    self_preference_warning,
    trace_digest,
)
from forge.domain.rules.text import fr_number, normalize, one_line
from forge.domain.scoring import (
    ErrorFact,
    JudgeInfo,
    composite_usage,
    compute_composite,
    criterion_values,
    score_criteria,
)
from forge.domain.serialization import list_from_dicts
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.domain.types import (
    CompositeResult,
    CriterionScore,
    CriterionSpec,
    DetectedError,
    EvaluationContext,
    EvaluationResult,
    EvidenceRef,
    ScoreConfig,
    TokenUsage,
    TraceEventView,
    to_dict,
)
from forge.infra import cache
from forge.infra.db import utcnow
from forge.infra.llm import client_from_credentials, estimate_cost
from forge.infra.models import (
    CompositeScore,
    ErrorType,
    Evaluation,
    EvaluationConfig,
    EvaluationRun,
    ExecutionTrace,
    Job,
    JudgeCacheEntry,
    RunError,
    Scenario,
    Score,
    TraceEvent,
)
from forge.infra.observability.metrics import (
    RUN_EVALUATION_SECONDS,
    record_error_detected,
    record_judge_call,
)
from forge.infra.queue import PRIORITY_INTERACTIVE, PermanentJobError, enqueue_job
from forge.services import audit
from forge.services import feedback as feedback_service
from forge.services import runs as run_service
from forge.services.access import Viewer, can_view_scenario
from forge.services.credentials import resolve_credentials
from forge.services.mapping import RunSpecs, load_criteria_catalog, load_score_config, specs_from_manifest

logger = logging.getLogger("forge.evaluation")

EXECUTION_ERROR_TYPES = frozenset(
    {BuiltinErrorType.EXECUTION_ERROR, BuiltinErrorType.TIMEOUT, BuiltinErrorType.BUDGET_EXCEEDED}
)
RUNNER_EVALUATOR_KEY = "runner"
EVALUATION_FAILURE_PREFIX = "Échec du traitement (evaluate_run)"
MAX_STATUS_DETAIL = 1000


class EvaluationStateError(ValueError):
    """Operation not allowed in the run's current state (French message)."""


# =====================================================================================================
# Loading
# =====================================================================================================


def event_view(row: TraceEvent) -> TraceEventView:
    return TraceEventView(
        id=str(row.id),
        seq=row.seq,
        type=row.type,
        name=row.name,
        offset_ms=float(row.offset_ms or 0.0),
        duration_ms=row.duration_ms,
        status=row.status,
        input=row.input,
        output=row.output,
        attributes=dict(row.attributes or {}),
        parent_id=str(row.parent_id) if row.parent_id else None,
    )


async def load_events(session: AsyncSession, run_id: uuid.UUID) -> list[TraceEventView]:
    rows = await session.scalars(
        select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq)
    )
    return [event_view(r) for r in rows]


async def load_trace(session: AsyncSession, run_id: uuid.UUID) -> ExecutionTrace | None:
    return await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run_id))


async def error_type_labels(session: AsyncSession) -> dict[str, str]:
    """Taxonomy codes → labels (table ``error_types``, built-ins as fallback)."""
    labels = {code: info.label for code, info in BUILTIN_ERROR_TYPES.items()}
    for row in await session.scalars(select(ErrorType)):
        labels[row.code] = row.label
    return labels


def build_context(
    run: EvaluationRun,
    specs: RunSpecs,
    config: ScoreConfig,
    trace: ExecutionTrace | None,
    events: list[TraceEventView],
) -> EvaluationContext:
    return EvaluationContext(
        run_id=str(run.id),
        scenario=specs.scenario,
        agent=specs.agent,
        config=config,
        output_text=(trace.output_text if trace else None) or "",
        output_json=trace.output_json if trace else None,
        events=events,
        token_usage=TokenUsage(
            input_tokens=int(trace.input_tokens if trace else 0),
            output_tokens=int(trace.output_tokens if trace else 0),
        ),
        estimated_cost=trace.estimated_cost if trace else None,
        latency_ms=trace.total_latency_ms if trace else None,
        run_error=run.error,
    )


def criteria_map(
    catalog: dict[str, CriterionSpec], specs: RunSpecs, config: ScoreConfig
) -> dict[str, CriterionSpec]:
    """Catalog overridden by the configuration then the scenario (weights, names, scales)."""
    merged = dict(catalog)
    merged.update({c.key: c for c in config.criteria})
    merged.update({c.key: c for c in specs.scenario.criteria})
    return merged


def rule_weights(specs: RunSpecs, config: ScoreConfig) -> dict[str, float]:
    return {r.id: float(r.weight) for r in [*specs.scenario.rules, *config.rules]}


def judge_infos(config: ScoreConfig) -> dict[str, JudgeInfo]:
    return {j.ref: JudgeInfo(key=j.key, weight=float(j.weight)) for j in config.judges}


async def resolve_round_config(
    session: AsyncSession, run: EvaluationRun, config_id: uuid.UUID | None
) -> tuple[ScoreConfig, uuid.UUID]:
    """Manifest configuration, or another stored configuration for a what-if re-evaluation."""
    if config_id is None or config_id == run.evaluation_config_id:
        return specs_from_manifest(run.manifest).config, run.evaluation_config_id
    row = await session.get(EvaluationConfig, config_id)
    if row is None:
        raise PermanentJobError(f"Configuration d'évaluation {config_id} introuvable")
    return await load_score_config(session, row), row.id


# =====================================================================================================
# Persistence helpers
# =====================================================================================================


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def evaluation_row(
    result: EvaluationResult, *, run_id: uuid.UUID, round_no: int | None, config_id: uuid.UUID | None
) -> Evaluation:
    return Evaluation(
        id=uuid.uuid4(),
        run_id=run_id,
        round=round_no,
        evaluation_config_id=config_id,
        evaluator_kind=result.evaluator_kind,
        evaluator_key=result.evaluator_key,
        criterion_key=result.criterion_key,
        dimension=result.dimension,
        raw_score=float(result.raw_score),
        scale_min=float(result.scale_min),
        scale_max=float(result.scale_max),
        normalized_score=float(result.normalized),
        confidence=float(max(0.0, min(1.0, result.confidence))),
        explanation=(result.explanation or "").strip() or "Verdict sans détail.",
        evidence=[to_dict(e) for e in result.evidence],
        errors=[to_dict(e) for e in result.errors],
        passed=result.passed,
        judge_id=_uuid(result.judge_id),
        judge_version=result.judge_version,
        prompt_hash=result.prompt_hash,
        model=result.model,
        raw_response=audit.jsonable(result.raw_response),
        latency_ms=result.latency_ms,
        cost=result.cost,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cached=result.cached,
    )


def result_from_row(row: Evaluation) -> EvaluationResult:
    return EvaluationResult(
        evaluator_kind=row.evaluator_kind,
        evaluator_key=row.evaluator_key,
        criterion_key=row.criterion_key,
        dimension=row.dimension,
        raw_score=row.raw_score,
        scale_min=row.scale_min,
        scale_max=row.scale_max,
        explanation=row.explanation,
        confidence=row.confidence,
        evidence=list_from_dicts(EvidenceRef, row.evidence),
        errors=list_from_dicts(DetectedError, row.errors),
        passed=row.passed,
        judge_id=str(row.judge_id) if row.judge_id else None,
        judge_version=row.judge_version,
        prompt_hash=row.prompt_hash,
        model=row.model,
        raw_response=row.raw_response,
        latency_ms=row.latency_ms,
        cost=row.cost,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        cached=row.cached,
    )


def score_rows(
    scores: Sequence[CriterionScore],
    used: Sequence[bool],
    evaluation_ids: Sequence[uuid.UUID],
    *,
    run_id: uuid.UUID,
    round_no: int,
    config_id: uuid.UUID,
) -> list[Score]:
    return [
        Score(
            run_id=run_id,
            round=round_no,
            evaluation_config_id=config_id,
            criterion_key=s.criterion_key,
            dimension=s.dimension,
            value=s.value,
            weight=s.weight,
            source=s.source,
            confidence=s.confidence,
            explanation=s.explanation.strip() or "Score calculé.",
            method=s.method,
            n_evaluations=s.n_evaluations,
            spread=s.spread,
            evaluation_ids=[str(evaluation_ids[i]) for i in s.evaluation_indexes],
            used_in_composite=flag,
        )
        for s, flag in zip(scores, used, strict=True)
    ]


def composite_row(
    composite: CompositeResult, *, run_id: uuid.UUID, round_no: int, config_id: uuid.UUID
) -> CompositeScore:
    return CompositeScore(
        run_id=run_id,
        round=round_no,
        evaluation_config_id=config_id,
        value=composite.value,
        raw_value=composite.raw_value,
        passed=composite.passed,
        gate_failed=composite.gate_failed,
        dimensions=[to_dict(d) for d in composite.dimensions],
        gates=[to_dict(g) for g in composite.gates],
        missing_dimensions=list(composite.missing_dimensions),
        formula=composite.formula,
    )


# =====================================================================================================
# Errors (§7.6)
# =====================================================================================================


@dataclass(slots=True)
class ErrorCandidate:
    error: DetectedError
    evaluator_kind: EvaluatorKind | None
    evaluator_key: str
    evaluation_index: int | None


@dataclass(slots=True)
class MergedError:
    type: str
    severity: ErrorSeverity
    description: str
    evidence: list[EvidenceRef]
    criterion_key: str | None
    evaluator_kind: EvaluatorKind | None
    evaluator_key: str
    evaluation_index: int | None
    evaluators: list[str] = field(default_factory=list)


def _evidence_signature(evidence: Sequence[EvidenceRef]) -> tuple[tuple[str, int | None], ...]:
    return tuple(sorted({(normalize(e.excerpt or "")[:200], e.trace_event_seq) for e in evidence}))


def merge_errors(candidates: Sequence[ErrorCandidate], known_types: set[str]) -> list[MergedError]:
    """Same type + same evidence + same criterion within a round → one error (evaluators listed)."""
    merged: dict[tuple[Any, ...], MergedError] = {}
    for candidate in candidates:
        error = candidate.error
        code = str(error.type or "").strip()
        description = (error.description or "").strip()
        if code not in known_types:
            description = f"[type d'origine : {code or '(absent)'}] {description}".strip()
            code = BuiltinErrorType.BAD_REASONING.value
        try:
            severity = ErrorSeverity(error.severity)
        except ValueError:
            severity = ErrorSeverity.medium
        signature = (code, error.criterion_key, _evidence_signature(error.evidence))
        kind = candidate.evaluator_kind.value if candidate.evaluator_kind else RUNNER_EVALUATOR_KEY
        label = f"{kind}:{candidate.evaluator_key}"
        existing = merged.get(signature)
        if existing is None:
            merged[signature] = MergedError(
                type=code,
                severity=severity,
                description=description
                or BUILTIN_ERROR_TYPES.get(code, BUILTIN_ERROR_TYPES["BAD_REASONING"]).label,
                evidence=list(error.evidence),
                criterion_key=error.criterion_key,
                evaluator_kind=candidate.evaluator_kind,
                evaluator_key=candidate.evaluator_key,
                evaluation_index=candidate.evaluation_index,
                evaluators=[label],
            )
            continue
        if label not in existing.evaluators:
            existing.evaluators.append(label)
        if SEVERITY_RANK[severity] > SEVERITY_RANK[existing.severity]:
            existing.severity = severity
    for item in merged.values():
        if len(item.evaluators) > 1:
            item.description = f"{item.description} (détectée par : {', '.join(item.evaluators)})"
    return list(merged.values())


def _first_event_id(
    evidence: Sequence[EvidenceRef], events_by_seq: dict[int, TraceEventView]
) -> uuid.UUID | None:
    for ref in evidence:
        if ref.trace_event_id:
            parsed = _uuid(ref.trace_event_id)
            if parsed is not None:
                return parsed
        if ref.trace_event_seq is not None and ref.trace_event_seq in events_by_seq:
            return _uuid(events_by_seq[ref.trace_event_seq].id)
    return None


def _resolve_evidence(
    evidence: Sequence[EvidenceRef], events_by_seq: dict[int, TraceEventView]
) -> list[EvidenceRef]:
    resolved = []
    for ref in evidence:
        if (
            ref.trace_event_id is None
            and ref.trace_event_seq is not None
            and ref.trace_event_seq in events_by_seq
        ):
            ref = EvidenceRef(
                excerpt=ref.excerpt,
                trace_event_id=events_by_seq[ref.trace_event_seq].id,
                trace_event_seq=ref.trace_event_seq,
                location=ref.location,
            )
        resolved.append(ref)
    return resolved


async def ensure_execution_error(
    session: AsyncSession, run: EvaluationRun, known_types: set[str]
) -> RunError | None:
    """Record the execution failure (``round=NULL``) once per run."""
    if not run.error:
        return None
    code = run.error_type if run.error_type in known_types else BuiltinErrorType.EXECUTION_ERROR.value
    existing = await session.scalar(
        select(RunError).where(
            RunError.run_id == run.id, RunError.round.is_(None), RunError.error_type == code
        )
    )
    if existing is not None:
        return existing
    info = BUILTIN_ERROR_TYPES.get(code)
    row = RunError(
        run_id=run.id,
        round=None,
        error_type=code,
        severity=info.default_severity if info else ErrorSeverity.high,
        description=one_line(run.error, 2000) or "Erreur d'exécution",
        evidence=[],
        evaluator_kind=None,
        evaluator_key=RUNNER_EVALUATOR_KEY,
    )
    session.add(row)
    record_error_detected(row.error_type, row.severity.value)
    return row


# =====================================================================================================
# Judges
# =====================================================================================================


@dataclass(slots=True)
class _JudgePlan:
    run: JudgeRun
    client: Any = None
    cache_key: str | None = None


async def _run_judges(
    session: AsyncSession,
    ctx: EvaluationContext,
    config: ScoreConfig,
    catalog: dict[str, CriterionSpec],
    labels: dict[str, str],
    warnings: list[str],
) -> list[JudgeRun]:
    if not config.judges:
        warnings.append("Aucun juge actif dans la configuration : critères jugés non évalués.")
        return []
    criteria = judged_criteria(ctx.scenario, config, catalog)
    digest = trace_digest(ctx.events)
    known = list(labels)
    finished: list[JudgeRun] = []
    pending: list[_JudgePlan] = []
    for judge in config.judges:
        selected = criteria_for_judge(judge, criteria)
        if not selected:
            continue
        warning = self_preference_warning(judge, ctx.agent)
        if warning:
            warnings.append(warning)
        prompt = render_prompt(judge, ctx, selected, labels)
        judge_run = JudgeRun(judge=judge, criteria=selected, prompt=prompt, model=judge.model)
        is_heuristic = JudgeProvider(judge.provider) == JudgeProvider.heuristic
        cache_key: str | None = None
        if settings.judge_cache_enabled and not is_heuristic:
            cache_key = judge_cache_key(
                judge_content_hash=judge.content_hash or judge.ref,
                scenario_content_hash=ctx.scenario.content_hash,
                output_text=ctx.output_text,
                output_json=ctx.output_json,
                trace_digest=digest,
                criteria_keys=[c.key for c in selected],
            )
            entry = await session.get(JudgeCacheEntry, cache_key)
            if entry is not None:
                parse_stored_response(judge_run, entry.response, ctx=ctx, known_error_types=known)
                if judge_run.status != "failed":
                    entry.hits += 1
                    record_judge_call(str(judge.provider), "cached", 0.0)
                    finished.append(judge_run)
                    continue
                judge_run = JudgeRun(judge=judge, criteria=selected, prompt=prompt, model=judge.model)
        client = None
        if not is_heuristic:
            credentials = await resolve_credentials(session, judge.credential_id)
            try:
                client = client_from_credentials(str(judge.provider), credentials, base_url=judge.base_url)
            except ValueError as exc:
                judge_run.error = str(exc)
        pending.append(_JudgePlan(run=judge_run, client=client, cache_key=cache_key))

    async def call(plan: _JudgePlan) -> JudgeRun:
        judge = plan.run.judge
        if JudgeProvider(judge.provider) == JudgeProvider.heuristic:
            return await run_judge(judge, ctx, plan.run.criteria, error_types=labels, prompt=plan.run.prompt)
        throttle_key = f"judge:{judge.credential_id or judge.ref}"

        async def before_call() -> None:
            await cache.throttle(throttle_key, settings.provider_rate_limit_per_minute)

        return await run_judge(
            judge,
            ctx,
            plan.run.criteria,
            error_types=labels,
            client=plan.client,
            timeout_seconds=settings.judge_timeout_seconds,
            cost_fn=estimate_cost,
            before_call=before_call,
            prompt=plan.run.prompt,
        )

    outcomes = await asyncio.gather(*(call(plan) for plan in pending))
    for plan, outcome in zip(pending, outcomes, strict=True):
        provider = str(outcome.judge.provider)
        record_judge_call(provider, "success" if outcome.status != "failed" else "failure", outcome.cost)
        if plan.cache_key and outcome.status != "failed":
            await session.execute(
                pg_insert(JudgeCacheEntry)
                .values(
                    key=plan.cache_key,
                    judge_id=_uuid(outcome.judge.judge_id),
                    response=audit.jsonable(cache_payload(outcome)),
                    hits=0,
                    created_at=utcnow(),
                )
                .on_conflict_do_nothing(index_elements=["key"])
            )
        finished.append(outcome)
    for outcome in finished:
        if outcome.status == "failed":
            warnings.append(
                f"Juge {outcome.judge.ref} en échec : {one_line(outcome.error or 'erreur inconnue', 300)}"
            )
        elif outcome.parsed.missing:
            warnings.append(
                f"Juge {outcome.judge.ref} : pas de verdict pour {', '.join(outcome.parsed.missing)}"
            )
    judged_keys = {r.criterion_key for o in finished for r in o.results}
    unjudged = [c.key for c in criteria if c.key not in judged_keys]
    if unjudged:
        warnings.append(f"Critère(s) sans verdict de juge (dimensions renormalisées) : {', '.join(unjudged)}")
    order = {j.ref: i for i, j in enumerate(config.judges)}
    finished.sort(key=lambda r: order.get(r.judge.ref, 0))
    return finished


def _attach_prompts(
    rows: list[Evaluation], results: list[EvaluationResult], judge_runs: list[JudgeRun]
) -> None:
    """Store the rendered prompt once per judge call (first verdict), others reference it."""
    index_by_result = {id(r): i for i, r in enumerate(results)}
    for judge_run in judge_runs:
        if not judge_run.results:
            continue
        first_index = index_by_result.get(id(judge_run.results[0]))
        if first_index is None:
            continue
        first_row = rows[first_index]
        for position, result in enumerate(judge_run.results):
            index = index_by_result.get(id(result))
            if index is None:
                continue
            raw = dict(rows[index].raw_response or {})
            if position == 0:
                raw["prompt"] = judge_run.prompt.as_dict()
            else:
                raw["prompt_evaluation_id"] = str(first_row.id)
            rows[index].raw_response = raw


# =====================================================================================================
# Scoring (shared by evaluation and rescoring)
# =====================================================================================================


@dataclass(slots=True)
class ScoringOutcome:
    scores: list[CriterionScore]
    used: list[bool]
    composite: CompositeResult
    criteria: dict[str, CriterionSpec]


def compute_scores(
    results: Sequence[EvaluationResult],
    *,
    specs: RunSpecs,
    config: ScoreConfig,
    catalog: dict[str, CriterionSpec],
    error_facts: Sequence[ErrorFact],
    run_error: str | None,
) -> ScoringOutcome:
    criteria = criteria_map(catalog, specs, config)
    scores = score_criteria(
        results, config, criteria, rule_weights=rule_weights(specs, config), judges=judge_infos(config)
    )
    used = composite_usage(scores, config)
    failed_rules = {
        r.evaluator_key
        for r in results
        if EvaluatorKind(r.evaluator_kind) == EvaluatorKind.rule and r.passed is False
    }
    composite = compute_composite(
        scores,
        used,
        config,
        errors=error_facts,
        failed_rules=failed_rules,
        forced_zero_reason="exécution de l'agent en échec" if run_error else None,
    )
    return ScoringOutcome(scores=scores, used=used, composite=composite, criteria=criteria)


def feedback_input(
    outcome: ScoringOutcome,
    errors: Sequence[RunError | MergedError],
    *,
    run_error: str | None,
    labels: dict[str, str],
    cost: float | None,
    latency_ms: float | None,
) -> FeedbackInput:
    values = criterion_values(outcome.scores, outcome.used)
    criteria = [
        FeedbackCriterion(
            key=key,
            value=value,
            name=outcome.criteria[key].name if key in outcome.criteria else key,
            dimension=dimension,
        )
        for key, (dimension, value, _weight) in sorted(values.items())
    ]
    feedback_errors = []
    for error in errors:
        if isinstance(error, RunError):
            evidence = list_from_dicts(EvidenceRef, error.evidence)
            feedback_errors.append(
                FeedbackError(
                    type=error.error_type, severity=error.severity, description=error.description,
                    evidence=evidence, criterion_key=error.criterion_key, run_id=str(error.run_id),
                )
            )  # fmt: skip
        else:
            feedback_errors.append(
                FeedbackError(
                    type=error.type, severity=error.severity, description=error.description,
                    evidence=list(error.evidence), criterion_key=error.criterion_key,
                )
            )  # fmt: skip
    composite = outcome.composite
    return FeedbackInput(
        score=composite.value,
        passed=composite.passed,
        criteria=criteria,
        errors=feedback_errors,
        gate_failures=[f"{g.gate_id} : {g.detail}" for g in composite.gates if not g.passed],
        run_failed=run_error,
        cost=cost,
        latency_ms=latency_ms,
        error_labels=labels,
    )


# =====================================================================================================
# evaluate_run job
# =====================================================================================================


@dataclass(slots=True)
class EvaluationOutcome:
    run_id: uuid.UUID
    round: int
    evaluation_config_id: uuid.UUID
    composite: CompositeResult
    judges: list[dict[str, Any]]
    warnings: list[str]
    errors: int


async def evaluate_run(
    session: AsyncSession, run: EvaluationRun, *, evaluation_config_id: uuid.UUID | None = None
) -> EvaluationOutcome:
    """Full §7.1 pipeline for one run in ``evaluating`` status (flushes, does not commit)."""
    specs = specs_from_manifest(run.manifest)
    config, config_id = await resolve_round_config(session, run, evaluation_config_id)
    catalog = await load_criteria_catalog(session)
    labels = await error_type_labels(session)
    known_types = set(labels)
    trace = await load_trace(session, run.id)
    events = await load_events(session, run.id)
    ctx = build_context(run, specs, config, trace, events)
    round_no = run.evaluation_round + 1
    warnings: list[str] = []
    if trace is None and not run.error:
        warnings.append("Aucune trace d'exécution enregistrée : évaluation sur une sortie vide.")

    # 3–4. Deterministic evaluators (rules, metrics).
    results: list[EvaluationResult] = []
    for evaluator in deterministic_evaluators():
        results.extend(validate_results(evaluator, await evaluator.evaluate(ctx)))

    # 5. Judges.
    judge_runs: list[JudgeRun] = []
    if run.error:
        warnings.append("Exécution en échec : juges non sollicités (règles et métriques uniquement).")
    else:
        judge_runs = await _run_judges(session, ctx, config, catalog, labels, warnings)
    for judge_run in judge_runs:
        results.extend(judge_run.results)

    # 6. Verdicts.
    rows = [evaluation_row(r, run_id=run.id, round_no=round_no, config_id=config_id) for r in results]
    _attach_prompts(rows, results, judge_runs)
    session.add_all(rows)

    # Human evaluations (round NULL) apply to every round.
    human_rows = list(
        await session.scalars(
            select(Evaluation)
            .where(Evaluation.run_id == run.id, Evaluation.round.is_(None))
            .order_by(Evaluation.created_at, Evaluation.id)
        )
    )
    all_results = [*results, *[result_from_row(h) for h in human_rows]]
    all_ids = [*[r.id for r in rows], *[h.id for h in human_rows]]

    # 9. Errors (needed by the gates).
    candidates = [
        ErrorCandidate(
            error=e, evaluator_kind=r.evaluator_kind, evaluator_key=r.evaluator_key, evaluation_index=i
        )
        for i, r in enumerate(results)
        for e in r.errors
    ]
    merged = merge_errors(candidates, known_types)
    events_by_seq = {e.seq: e for e in events}
    error_rows: list[RunError] = []
    for item in merged:
        evidence = _resolve_evidence(item.evidence, events_by_seq)
        error_rows.append(
            RunError(
                run_id=run.id,
                round=round_no,
                error_type=item.type,
                severity=item.severity,
                description=item.description[:4000],
                evidence=[to_dict(e) for e in evidence],
                evaluator_kind=item.evaluator_kind,
                evaluator_key=item.evaluator_key,
                evaluation_id=rows[item.evaluation_index].id if item.evaluation_index is not None else None,
                trace_event_id=_first_event_id(evidence, events_by_seq),
                criterion_key=item.criterion_key,
            )
        )
    session.add_all(error_rows)
    execution_error = await ensure_execution_error(session, run, known_types)
    facts = [ErrorFact(type=e.error_type, severity=e.severity) for e in error_rows]
    if execution_error is not None:
        facts.append(ErrorFact(type=execution_error.error_type, severity=execution_error.severity))
    for human in human_rows:
        for error in human.errors or []:
            try:
                facts.append(
                    ErrorFact(type=str(error.get("type")), severity=ErrorSeverity(error.get("severity")))
                )
            except (ValueError, TypeError):
                continue
    for row in error_rows:
        record_error_detected(row.error_type, row.severity.value)

    # 7–8. Scores and composite.
    outcome = compute_scores(
        all_results, specs=specs, config=config, catalog=catalog, error_facts=facts, run_error=run.error
    )
    session.add_all(
        score_rows(
            outcome.scores, outcome.used, all_ids, run_id=run.id, round_no=round_no, config_id=config_id
        )
    )
    session.add(composite_row(outcome.composite, run_id=run.id, round_no=round_no, config_id=config_id))
    await session.flush()

    # 10. Feedback.
    feedback_errors: list[RunError | MergedError] = list(error_rows)
    if execution_error is not None:
        feedback_errors.append(execution_error)
    await feedback_service.create_run_feedback(
        session,
        run,
        round_no=round_no,
        data=feedback_input(
            outcome,
            feedback_errors,
            run_error=run.error,
            labels=labels,
            cost=ctx.estimated_cost,
            latency_ms=ctx.latency_ms,
        ),
    )

    # Denormalisation (the latest round is the run's current evaluation).
    run.evaluation_round = round_no
    run.composite_score = outcome.composite.value
    run.passed = outcome.composite.passed
    run.gate_failed = outcome.composite.gate_failed
    judges_summary = [j.summary() for j in judge_runs]

    # 11. Audit.
    await audit.record(
        session,
        None,
        "run.evaluate",
        "evaluation_run",
        run.id,
        summary=(
            f"Évaluation du run (round {round_no}) : composite {fr_number(outcome.composite.value, 1)}/100"
            f"{' — garde-fou en échec' if outcome.composite.gate_failed else ''}"
        ),
        details={
            "round": round_no,
            "evaluation_config_id": str(config_id),
            "config": {"key": config.key, "version": config.version},
            "judges": judges_summary,
            "composite": outcome.composite.value,
            "raw_composite": outcome.composite.raw_value,
            "passed": outcome.composite.passed,
            "gate_failed": outcome.composite.gate_failed,
            "gates": [to_dict(g) for g in outcome.composite.gates if not g.passed],
            "missing_dimensions": outcome.composite.missing_dimensions,
            "evaluations": len(rows),
            "errors": len(error_rows),
            "warnings": warnings,
            "execution_error": run.error_type if run.error else None,
        },
    )
    return EvaluationOutcome(
        run_id=run.id,
        round=round_no,
        evaluation_config_id=config_id,
        composite=outcome.composite,
        judges=judges_summary,
        warnings=warnings,
        errors=len(error_rows),
    )


async def evaluate_run_job(session: AsyncSession, job: Job) -> None:
    """Handler of ``evaluate_run`` jobs (payload: optional ``evaluation_config_id``)."""
    if job.run_id is None:
        raise PermanentJobError("Job evaluate_run sans run")
    run = await session.get(EvaluationRun, job.run_id)
    if run is None:
        raise PermanentJobError(f"Run {job.run_id} introuvable")
    if run.status != RunStatus.evaluating:
        logger.info("Run %s is %s: evaluation skipped", run.id, run.status)
        return
    config_id = _uuid((job.payload or {}).get("evaluation_config_id"))
    started = time.perf_counter()
    outcome = await evaluate_run(session, run, evaluation_config_id=config_id)
    RUN_EVALUATION_SECONDS.observe(time.perf_counter() - started)
    detail = "; ".join(outcome.warnings)[:MAX_STATUS_DETAIL] or None
    if run.error:
        await run_service.mark_failed(
            session, run, run.error, error_type=run.error_type or BuiltinErrorType.EXECUTION_ERROR.value
        )
    else:
        await run_service.mark_completed(session, run)
    run.status_detail = detail
    await session.flush()
    logger.info(
        "Run %s evaluated (round %d): composite %.1f, %d error(s), %d warning(s)",
        run.id, outcome.round, outcome.composite.value, outcome.errors, len(outcome.warnings),
    )  # fmt: skip


# =====================================================================================================
# Rescoring (no judge call)
# =====================================================================================================


@dataclass(slots=True)
class RescoreResult:
    run_id: uuid.UUID
    round: int
    evaluation_config_id: uuid.UUID | None
    composite: CompositeResult
    scores: list[CriterionScore]
    used: list[bool]
    previous_composite: float | None = None


async def round_config_id(session: AsyncSession, run: EvaluationRun, round_no: int) -> uuid.UUID:
    """Configuration used by a stored round (the run's own one unless re-evaluated otherwise)."""
    value = await session.scalar(
        select(CompositeScore.evaluation_config_id)
        .where(CompositeScore.run_id == run.id, CompositeScore.round == round_no)
        .order_by(CompositeScore.created_at.desc())
        .limit(1)
    )
    return value or run.evaluation_config_id


async def rescore_run(
    session: AsyncSession,
    run: EvaluationRun,
    *,
    config: ScoreConfig | EvaluationConfig | None = None,
    persist: bool = True,
    actor: Any = None,
) -> RescoreResult | None:
    """Recompute scores and composite of the current round from stored verdicts (no judge call).

    * ``config=None``: the configuration of the current round (used after a human evaluation);
    * ``config``: another configuration (preview) — stored verdicts are re-weighted / re-aggregated
      and gates re-applied; judges or rules absent from the stored round are not executed.

    With ``persist`` the round's ``scores`` / ``composite_scores`` of that configuration are replaced,
    the run feedback is regenerated and (for the round's own configuration) the run denormalised.
    Returns ``None`` when the run has never been evaluated.
    """
    round_no = run.evaluation_round
    if round_no <= 0:
        return None
    specs = specs_from_manifest(run.manifest)
    current_config_id = await round_config_id(session, run, round_no)
    target_id: uuid.UUID | None
    if config is None:
        score_config, target_id = await resolve_round_config(session, run, current_config_id)
    elif isinstance(config, EvaluationConfig):
        score_config, target_id = await load_score_config(session, config), config.id
    else:
        score_config, target_id = config, _uuid(config.config_id)
    catalog = await load_criteria_catalog(session)
    rows = list(
        await session.scalars(
            select(Evaluation)
            .where(Evaluation.run_id == run.id, (Evaluation.round == round_no) | Evaluation.round.is_(None))
            .order_by(Evaluation.round.is_(None), Evaluation.created_at, Evaluation.id)
        )
    )
    results = [result_from_row(r) for r in rows]
    errors = list(
        await session.scalars(
            select(RunError).where(
                RunError.run_id == run.id, (RunError.round == round_no) | RunError.round.is_(None)
            )
        )
    )
    facts = [ErrorFact(type=e.error_type, severity=e.severity) for e in errors]
    for row in rows:
        if row.evaluator_kind == EvaluatorKind.human:
            for error in row.errors or []:
                try:
                    facts.append(
                        ErrorFact(type=str(error.get("type")), severity=ErrorSeverity(error.get("severity")))
                    )
                except (ValueError, TypeError):
                    continue
    outcome = compute_scores(
        results, specs=specs, config=score_config, catalog=catalog, error_facts=facts, run_error=run.error
    )
    previous = await session.scalar(
        select(CompositeScore.value).where(
            CompositeScore.run_id == run.id,
            CompositeScore.round == round_no,
            CompositeScore.evaluation_config_id == (target_id or current_config_id),
        )
    )
    result = RescoreResult(
        run_id=run.id,
        round=round_no,
        evaluation_config_id=target_id,
        composite=outcome.composite,
        scores=outcome.scores,
        used=outcome.used,
        previous_composite=previous if previous is not None else run.composite_score,
    )
    if not persist:
        return result
    if target_id is None:
        raise ValueError("Une configuration enregistrée est requise pour persister un recalcul")
    await session.execute(
        delete(Score).where(
            Score.run_id == run.id, Score.round == round_no, Score.evaluation_config_id == target_id
        )
    )
    await session.execute(
        delete(CompositeScore).where(
            CompositeScore.run_id == run.id,
            CompositeScore.round == round_no,
            CompositeScore.evaluation_config_id == target_id,
        )
    )
    session.add_all(
        score_rows(
            outcome.scores,
            outcome.used,
            [r.id for r in rows],
            run_id=run.id,
            round_no=round_no,
            config_id=target_id,
        )
    )
    session.add(composite_row(outcome.composite, run_id=run.id, round_no=round_no, config_id=target_id))
    if target_id == current_config_id:
        run.composite_score = outcome.composite.value
        run.passed = outcome.composite.passed
        run.gate_failed = outcome.composite.gate_failed
        labels = await error_type_labels(session)
        trace = await load_trace(session, run.id)
        await feedback_service.create_run_feedback(
            session,
            run,
            round_no=round_no,
            data=feedback_input(
                outcome,
                errors,
                run_error=run.error,
                labels=labels,
                cost=trace.estimated_cost if trace else None,
                latency_ms=trace.total_latency_ms if trace else None,
            ),
            replace=True,
        )
    await audit.record(
        session,
        actor,
        "run.rescore",
        "evaluation_run",
        run.id,
        summary=(
            f"Recalcul du score (round {round_no}) : {fr_number(result.previous_composite or 0, 1)} → "
            f"{fr_number(outcome.composite.value, 1)}"
        ),
        details={
            "round": round_no,
            "evaluation_config_id": str(target_id),
            "previous": result.previous_composite,
            "composite": outcome.composite.value,
            "gate_failed": outcome.composite.gate_failed,
            "use_human_scores": score_config.use_human_scores,
        },
    )
    await session.flush()
    return result


# =====================================================================================================
# Re-evaluation & access
# =====================================================================================================


async def start_reevaluation(
    session: AsyncSession,
    run: EvaluationRun,
    *,
    config: EvaluationConfig | None = None,
    actor: Any = None,
) -> Job | None:
    """Queue a new evaluation round (optionally with another configuration). Flushes only.

    Raises :class:`EvaluationStateError` unless the run is ``completed`` or ``failed``.
    """
    if run.status not in (RunStatus.completed, RunStatus.failed):
        raise EvaluationStateError(
            f"Ré-évaluation impossible : le run est « {run.status.value} » (terminé ou en échec attendu)"
        )
    if run.error and run.error.startswith(EVALUATION_FAILURE_PREFIX):
        # The evaluation crashed earlier, not the agent: the execution itself succeeded.
        run.error = None
        run.error_type = None
    executed_at = run.executed_at
    await run_service.mark_evaluating(session, run, enqueue=False)
    run.executed_at = executed_at
    run.status_detail = "Ré-évaluation en attente"
    payload: dict[str, Any] = {}
    if config is not None and config.id != run.evaluation_config_id:
        payload["evaluation_config_id"] = str(config.id)
    job = await enqueue_job(
        session,
        JobKind.evaluate_run,
        run_id=run.id,
        payload=payload,
        priority=PRIORITY_INTERACTIVE,
        max_attempts=3,
        dedupe_key=f"evaluate_run:{run.id}",
    )
    await audit.record(
        session,
        actor,
        "run.reevaluate",
        "evaluation_run",
        run.id,
        summary=f"Ré-évaluation demandée (round {run.evaluation_round + 1})",
        details={
            "next_round": run.evaluation_round + 1,
            "evaluation_config_id": payload.get("evaluation_config_id"),
        },
    )
    await session.flush()
    return job


async def get_run_for_viewer(
    session: AsyncSession, run_id: uuid.UUID, viewer: Viewer
) -> tuple[EvaluationRun, Scenario] | None:
    """Run and its scenario, or ``None`` when absent or above the viewer's clearance (→ 404)."""
    run = await session.get(EvaluationRun, run_id)
    if run is None:
        return None
    scenario = await session.get(Scenario, run.scenario_id)
    if scenario is None or not can_view_scenario(viewer, scenario):
        return None
    return run, scenario


# =====================================================================================================
# Read models (API)
# =====================================================================================================


async def evaluation_rounds(session: AsyncSession, run_id: uuid.UUID) -> list[int]:
    rows = await session.scalars(
        select(CompositeScore.round)
        .where(CompositeScore.run_id == run_id)
        .distinct()
        .order_by(CompositeScore.round)
    )
    return [int(r) for r in rows]


def resolve_round(run: EvaluationRun, requested: int | None) -> int | None:
    if requested is not None:
        return requested
    return run.evaluation_round or None


async def round_evaluations(
    session: AsyncSession,
    run_id: uuid.UUID,
    round_no: int | None,
    *,
    include_human: bool = True,
    kind: EvaluatorKind | None = None,
    criterion_key: str | None = None,
) -> list[Evaluation]:
    """Verdicts of a round (+ human evaluations, which apply to every round)."""
    condition = Evaluation.round == round_no if round_no is not None else Evaluation.round.is_(None)
    if include_human and round_no is not None:
        condition = condition | Evaluation.round.is_(None)
    query = select(Evaluation).where(Evaluation.run_id == run_id, condition)
    if kind is not None:
        query = query.where(Evaluation.evaluator_kind == kind)
    if criterion_key:
        query = query.where(Evaluation.criterion_key == criterion_key)
    rows = await session.scalars(query.order_by(Evaluation.created_at, Evaluation.id))
    return list(rows)


async def round_composite(
    session: AsyncSession, run_id: uuid.UUID, round_no: int | None
) -> CompositeScore | None:
    if round_no is None:
        return None
    return await session.scalar(
        select(CompositeScore)
        .where(CompositeScore.run_id == run_id, CompositeScore.round == round_no)
        .order_by(CompositeScore.created_at.desc())
        .limit(1)
    )


async def round_scores(
    session: AsyncSession, run_id: uuid.UUID, round_no: int | None, config_id: uuid.UUID | None = None
) -> list[Score]:
    if round_no is None:
        return []
    query = select(Score).where(Score.run_id == run_id, Score.round == round_no)
    if config_id is not None:
        query = query.where(Score.evaluation_config_id == config_id)
    return list(await session.scalars(query.order_by(Score.dimension, Score.criterion_key, Score.source)))


async def round_errors(session: AsyncSession, run_id: uuid.UUID, round_no: int | None) -> list[RunError]:
    condition = RunError.round.is_(None)
    if round_no is not None:
        condition = condition | (RunError.round == round_no)
    rows = await session.scalars(
        select(RunError)
        .where(RunError.run_id == run_id, condition)
        .order_by(RunError.created_at, RunError.id)
    )
    items = list(rows)
    items.sort(key=lambda e: -SEVERITY_RANK[ErrorSeverity(e.severity)])
    return items


async def event_seqs(session: AsyncSession, ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, TraceEvent]:
    if not ids:
        return {}
    rows = await session.scalars(select(TraceEvent).where(TraceEvent.id.in_(list(ids))))
    return {r.id: r for r in rows}


@dataclass(slots=True)
class Provenance:
    """Everything needed to answer « where does this score come from? » (docs §23 audit questions)."""

    run: EvaluationRun
    round: int
    criterion: CriterionSpec
    config: ScoreConfig
    config_id: uuid.UUID
    scores: list[Score]
    evaluations: list[Evaluation]
    prompts: dict[uuid.UUID, dict[str, Any]]
    judges: dict[str, Any]
    rules: dict[str, tuple[Any, str]]
    events: dict[int, TraceEvent]
    composite: CompositeScore | None
    errors: list[RunError]


async def score_provenance(
    session: AsyncSession, run: EvaluationRun, criterion_key: str, round_no: int | None = None
) -> Provenance | None:
    """Evaluators, judge versions & prompts, rules & params, trace events, aggregation of a criterion."""
    round_no = resolve_round(run, round_no)
    if round_no is None:
        return None
    composite = await round_composite(session, run.id, round_no)
    config_id = composite.evaluation_config_id if composite else run.evaluation_config_id
    scores = await round_scores(session, run.id, round_no, config_id)
    scores = [s for s in scores if s.criterion_key == criterion_key]
    evaluations = await round_evaluations(session, run.id, round_no, criterion_key=criterion_key)
    if not scores and not evaluations:
        return None
    specs = specs_from_manifest(run.manifest)
    config, _ = await resolve_round_config(session, run, config_id)
    catalog = criteria_map(await load_criteria_catalog(session), specs, config)
    criterion = catalog.get(criterion_key)
    if criterion is None:
        first = evaluations[0] if evaluations else None
        criterion = CriterionSpec(
            key=criterion_key,
            dimension=first.dimension if first else scores[0].dimension,
            name=criterion_key,
            scale_min=first.scale_min if first else 0.0,
            scale_max=first.scale_max if first else 1.0,
        )
    # Rendered prompts: stored on the first verdict of each judge call.
    prompt_ids: set[uuid.UUID] = set()
    for row in evaluations:
        raw = row.raw_response if isinstance(row.raw_response, dict) else {}
        ref = _uuid(raw.get("prompt_evaluation_id"))
        if ref is not None:
            prompt_ids.add(ref)
    prompts: dict[uuid.UUID, dict[str, Any]] = {}
    for row in evaluations:
        raw = row.raw_response if isinstance(row.raw_response, dict) else {}
        if isinstance(raw.get("prompt"), dict):
            prompts[row.id] = raw["prompt"]
    missing = prompt_ids - set(prompts)
    if missing:
        for row in await session.scalars(select(Evaluation).where(Evaluation.id.in_(list(missing)))):
            raw = row.raw_response if isinstance(row.raw_response, dict) else {}
            if isinstance(raw.get("prompt"), dict):
                prompts[row.id] = raw["prompt"]
    judges = {j.ref: j for j in config.judges}
    for judge in specs.config.judges:
        judges.setdefault(judge.ref, judge)
    rules: dict[str, tuple[Any, str]] = {r.id: (r, "scenario") for r in specs.scenario.rules}
    rules.update({r.id: (r, "configuration") for r in config.rules})
    seqs: set[int] = set()
    event_ids: set[uuid.UUID] = set()
    for row in evaluations:
        for ref in [*(row.evidence or []), *[ev for e in row.errors or [] for ev in e.get("evidence") or []]]:
            if ref.get("trace_event_seq") is not None:
                seqs.add(int(ref["trace_event_seq"]))
            parsed = _uuid(ref.get("trace_event_id"))
            if parsed is not None:
                event_ids.add(parsed)
    events: dict[int, TraceEvent] = {}
    if seqs or event_ids:
        condition = TraceEvent.seq.in_(list(seqs)) if seqs else None
        if event_ids:
            id_condition = TraceEvent.id.in_(list(event_ids))
            condition = id_condition if condition is None else condition | id_condition
        for event in await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run.id, condition)):
            events[event.seq] = event
    errors = [e for e in await round_errors(session, run.id, round_no) if e.criterion_key == criterion_key]
    return Provenance(
        run=run,
        round=round_no,
        criterion=criterion,
        config=config,
        config_id=config_id,
        scores=scores,
        evaluations=evaluations,
        prompts=prompts,
        judges=judges,
        rules=rules,
        events=events,
        composite=composite,
        errors=errors,
    )
