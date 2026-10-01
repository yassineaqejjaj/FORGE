"""Feedback reports (docs/ARCHITECTURE.md §7.7): run reports and aggregated reports.

* :func:`create_run_feedback` — called by the evaluation engine for each round;
* :func:`create_aggregate_feedback` — report over a set of runs (benchmark per agent version,
  experiment), used by the analytics module;
* optional LLM synthesis when ``FORGE_FEEDBACK_LLM_*`` is configured: it rewrites the summary and the
  recommendation texts only (categories, priorities, related errors/criteria and evidence stay the
  deterministic ones — the LLM never invents evidence); any failure keeps the deterministic report.

Services flush only; callers commit.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import FeedbackScope, ScenarioVisibility
from forge.domain.feedback import (
    FeedbackCriterion,
    FeedbackError,
    FeedbackInput,
    build_feedback,
    build_group_feedback,
)
from forge.domain.redaction import REDACTED_TEXT, is_private
from forge.domain.rules.extraction import extract_json_object
from forge.domain.serialization import list_from_dicts
from forge.domain.taxonomy import BUILTIN_ERROR_TYPES
from forge.domain.types import EvidenceRef, FeedbackReportData, to_dict
from forge.infra.llm import LLMError, get_client
from forge.infra.models import CompositeScore, ErrorType, EvaluationRun, FeedbackReport, RunError, Score
from forge.services import audit
from forge.services.mapping import load_criteria_catalog

logger = logging.getLogger("forge.feedback")

LLM_SYSTEM_PROMPT = (
    "Tu es un expert de l'amélioration d'agents IA. On te donne un rapport d'évaluation structuré "
    "(JSON). Reformule la synthèse et les recommandations pour qu'elles soient claires, concrètes et "
    "actionnables, en français. N'invente aucun fait, aucune preuve, aucune erreur : appuie-toi "
    "uniquement sur le rapport. Réponds uniquement avec un objet JSON."
)


# --- LLM synthesis ---------------------------------------------------------------------------------


async def _llm_enrich(report: FeedbackReportData) -> FeedbackReportData:
    if not settings.feedback_llm_enabled or not report.recommendations:
        return report
    payload = {
        "summary": report.summary,
        "score": report.score,
        "strengths": report.strengths,
        "weaknesses": report.weaknesses,
        "errors": [
            {k: e.get(k) for k in ("type", "label", "severity", "count", "examples")} for e in report.errors
        ],
        "recommendations": [
            {
                "index": i,
                "category": r.category.value,
                "title": r.title,
                "description": r.description,
                "rationale": r.rationale,
                "priority": r.priority.value,
            }
            for i, r in enumerate(report.recommendations)
        ],
    }
    instructions = (
        "Rapport :\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n\n"
        'Réponds avec {"summary": "...", "recommendations": [{"index": <n>, "title": "...", '
        '"description": "...", "rationale": "..."}]} — un objet par recommandation existante, même index.'
    )
    model = settings.feedback_llm_model
    try:
        client = get_client(
            "openai", api_key=settings.feedback_llm_api_key or None, base_url=settings.feedback_llm_base_url
        )
        response = await client.complete(
            system=LLM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": instructions}],
            model=model,
            temperature=0.2,
            max_tokens=2000,
            timeout_seconds=settings.judge_timeout_seconds,
        )
    except (LLMError, ValueError) as exc:
        logger.warning("Feedback LLM synthesis failed (%s): deterministic report kept", type(exc).__name__)
        return report
    data = extract_json_object(response.text)
    if not data:
        return report
    summary = str(data.get("summary") or "").strip()
    items = {
        int(i["index"]): i for i in data.get("recommendations") or [] if isinstance(i, dict) and "index" in i
    }
    for index, rec in enumerate(report.recommendations):
        item = items.get(index)
        if not item:
            continue
        rec.title = str(item.get("title") or rec.title).strip()[:300] or rec.title
        rec.description = str(item.get("description") or rec.description).strip()[:2000] or rec.description
        rec.rationale = str(item.get("rationale") or rec.rationale).strip()[:2000] or rec.rationale
    if summary:
        report.summary = summary[:3000]
    report.generator = f"llm:{response.model or model}"
    return report


# --- Persistence -----------------------------------------------------------------------------------


def _row(report: FeedbackReportData, **fields: Any) -> FeedbackReport:
    return FeedbackReport(
        summary=report.summary,
        score=report.score,
        strengths=list(report.strengths),
        weaknesses=list(report.weaknesses),
        errors=audit.jsonable(report.errors),
        recommendations=[to_dict(r) for r in report.recommendations],
        priority_actions=list(report.priority_actions),
        generator=report.generator,
        **fields,
    )


def report_data(row: FeedbackReport) -> dict[str, Any]:
    """Stable JSON form of a stored report (API, NOVA)."""
    return {
        "id": str(row.id),
        "scope": row.scope.value,
        "run_id": str(row.run_id) if row.run_id else None,
        "benchmark_execution_id": str(row.benchmark_execution_id) if row.benchmark_execution_id else None,
        "experiment_id": str(row.experiment_id) if row.experiment_id else None,
        "agent_version_id": str(row.agent_version_id) if row.agent_version_id else None,
        "round": row.round,
        "score": row.score,
        "summary": row.summary,
        "strengths": list(row.strengths or []),
        "weaknesses": list(row.weaknesses or []),
        "errors": list(row.errors or []),
        "recommendations": list(row.recommendations or []),
        "priority_actions": list(row.priority_actions or []),
        "generator": row.generator,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def create_run_feedback(
    session: AsyncSession,
    run: EvaluationRun,
    *,
    round_no: int,
    data: FeedbackInput,
    replace: bool = False,
) -> FeedbackReport:
    """Build (deterministic + optional LLM) and store the run report of ``round_no``."""
    agent = run.manifest.get("agent") or {}
    data.label = data.label or f"{agent.get('agent_name', 'Agent')} v{agent.get('version', '?')}"
    report = await _llm_enrich(build_feedback(data))
    if replace:
        await session.execute(
            delete(FeedbackReport).where(
                FeedbackReport.run_id == run.id,
                FeedbackReport.scope == FeedbackScope.run,
                FeedbackReport.round == round_no,
            )
        )
    row = _row(
        report, scope=FeedbackScope.run, run_id=run.id, agent_version_id=run.agent_version_id, round=round_no
    )
    session.add(row)
    await session.flush()
    return row


async def latest_run_feedback(
    session: AsyncSession, run_id: uuid.UUID, round_no: int | None = None
) -> FeedbackReport | None:
    query = select(FeedbackReport).where(
        FeedbackReport.run_id == run_id, FeedbackReport.scope == FeedbackScope.run
    )
    if round_no is not None:
        query = query.where(FeedbackReport.round == round_no)
    return await session.scalar(query.order_by(FeedbackReport.created_at.desc()).limit(1))


async def _labels(session: AsyncSession) -> dict[str, str]:
    labels = {code: info.label for code, info in BUILTIN_ERROR_TYPES.items()}
    for row in await session.scalars(select(ErrorType)):
        labels[row.code] = row.label
    return labels


async def create_aggregate_feedback(
    session: AsyncSession,
    *,
    scope: FeedbackScope | str,
    runs: Sequence[EvaluationRun],
    benchmark_execution_id: uuid.UUID | None = None,
    experiment_id: uuid.UUID | None = None,
    agent_version_id: uuid.UUID | None = None,
) -> FeedbackReport:
    """Aggregated report over ``runs`` (current round of each evaluated run). Flushes only.

    Evidence excerpts of private scenarios are dropped (aggregated reports are shared widely);
    the error descriptions of those runs are masked as well.
    """
    scope = FeedbackScope(scope)
    evaluated = [r for r in runs if r.evaluation_round > 0]
    run_ids = [r.id for r in evaluated]
    rounds = {r.id: r.evaluation_round for r in evaluated}
    composites: dict[uuid.UUID, CompositeScore] = {}
    scores: dict[uuid.UUID, list[Score]] = defaultdict(list)
    errors: dict[uuid.UUID, list[RunError]] = defaultdict(list)
    if run_ids:
        for comp in await session.scalars(select(CompositeScore).where(CompositeScore.run_id.in_(run_ids))):
            if comp.round == rounds[comp.run_id]:
                current = composites.get(comp.run_id)
                if current is None or comp.created_at > current.created_at:
                    composites[comp.run_id] = comp
        for score_row in await session.scalars(
            select(Score).where(Score.run_id.in_(run_ids), Score.used_in_composite.is_(True))
        ):
            if score_row.round == rounds[score_row.run_id]:
                scores[score_row.run_id].append(score_row)
        for error_row in await session.scalars(select(RunError).where(RunError.run_id.in_(run_ids))):
            if error_row.round is None or error_row.round == rounds[error_row.run_id]:
                errors[error_row.run_id].append(error_row)
    catalog = await load_criteria_catalog(session)
    labels = await _labels(session)
    inputs: list[FeedbackInput] = []
    for run in evaluated:
        private = is_private(str((run.manifest.get("scenario") or {}).get("visibility") or ""))
        composite = composites.get(run.id)
        per_criterion: dict[str, list[float]] = defaultdict(list)
        dims: dict[str, Any] = {}
        for score in scores[run.id]:
            if composite is not None and score.evaluation_config_id != composite.evaluation_config_id:
                continue
            per_criterion[score.criterion_key].append(score.value)
            dims[score.criterion_key] = score.dimension
        criteria = [
            FeedbackCriterion(
                key=key,
                value=sum(values) / len(values),
                name=catalog[key].name if key in catalog else key,
                dimension=dims[key],
            )
            for key, values in per_criterion.items()
        ]
        run_errors = [
            FeedbackError(
                type=e.error_type,
                severity=e.severity,
                description=REDACTED_TEXT if private else e.description,
                evidence=[] if private else list_from_dicts(EvidenceRef, e.evidence),
                criterion_key=e.criterion_key,
                run_id=str(run.id),
            )
            for e in errors[run.id]
        ]
        inputs.append(
            FeedbackInput(
                score=composite.value if composite else run.composite_score,
                passed=composite.passed if composite else run.passed,
                criteria=criteria,
                errors=run_errors,
                gate_failures=[
                    g.get("gate_id", "")
                    for g in (composite.gates if composite else [])
                    if not g.get("passed")
                ],
                run_failed=run.error,
                error_labels=labels,
            )
        )
    label = ""
    if evaluated:
        agents = {(r.manifest.get("agent") or {}).get("agent_version_id") for r in evaluated}
        if len(agents) == 1:
            agent = evaluated[0].manifest.get("agent") or {}
            label = f"{agent.get('agent_name', 'Agent')} v{agent.get('version', '?')}"
    report = await _llm_enrich(build_group_feedback(inputs, label=label))
    if len(runs) != len(evaluated):
        report.summary += f" ({len(runs) - len(evaluated)} run(s) non évalué(s) exclus.)"
    row = _row(
        report,
        scope=scope,
        benchmark_execution_id=benchmark_execution_id,
        experiment_id=experiment_id,
        agent_version_id=agent_version_id,
        round=None,
    )
    session.add(row)
    await session.flush()
    return row


# --- Redaction for the API ---------------------------------------------------------------------------


def redact_report(data: dict[str, Any]) -> dict[str, Any]:
    """Run report of a private scenario as seen by a non-maintainer: no evidence, no examples."""
    result = dict(data)
    result["errors"] = [
        {**e, "description": REDACTED_TEXT, "examples": [], "evidence": []} for e in data.get("errors") or []
    ]
    result["recommendations"] = [{**r, "evidence": []} for r in data.get("recommendations") or []]
    result["redacted"] = True
    return result


def visibility_is_private(run: EvaluationRun, current: ScenarioVisibility | str | None) -> bool:
    manifest_visibility = str((run.manifest.get("scenario") or {}).get("visibility") or "public")
    return is_private(manifest_visibility) or is_private(str(getattr(current, "value", current) or ""))
