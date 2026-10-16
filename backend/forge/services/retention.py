"""Retention and forgetting: what FORGE copied from ORBIT / agents does not live forever.

FORGE keeps copies of context and outputs: ``ExecutionTrace`` (input, outputs, messages), trace event
payloads, judge prompts and answers (``Evaluation.raw_response``), the judge cache, feedback evidence,
run manifests and the scenarios promoted from failed runs. Two mechanisms empty those *texts* while
keeping every measurement (scores, errors, tokens, costs, latencies, timeline structure):

* :func:`purge` — scheduled by the workers (and ``python -m forge.ops retention``), one rule per kind
  (``FORGE_RETENTION_*_DAYS``, ``0`` keeps), with a dry run, metrics and an audit entry;
* :func:`forget` — an authenticated request (or ORBIT's signed ``*.forgotten`` webhook) naming
  ``document_id`` / ``memory_item_id`` / ``lineage_id`` / ``task_id``: every copy of what matches is emptied.
  It is idempotent and acknowledges what it touched. Fail-closed choices: a run that received a matching
  document loses *all* its payloads (its output may quote the document), and the judge cache, which has no
  link to runs, is emptied when anything matched.

Services flush only; callers commit. This is technical framing, not legal advice.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, delete, func, null, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.redaction import REDACTED_TEXT
from forge.infra.db import utcnow
from forge.infra.models import (
    Evaluation,
    EvaluationRun,
    ExecutionTrace,
    FeedbackReport,
    JudgeCacheEntry,
    ScenarioVersion,
    TraceEvent,
)
from forge.infra.observability.metrics import FORGET_REQUESTS_TOTAL, RETENTION_PURGED_TOTAL
from forge.services import audit
from forge.services.audit import Actor, ActorLike
from forge.services.taxonomy import InvalidError

logger = logging.getLogger("forge.retention")

FORGOTTEN_TEXT = "[contenu oublié]"
MAX_IDS = 200
BATCH = 500
#: ``pg_try_advisory_xact_lock`` key: one scheduled purge at a time across workers.
PURGE_LOCK_KEY = 0x464F5247  # "FORG"


# =====================================================================================================
# Reports
# =====================================================================================================


@dataclass(slots=True)
class PurgeReport:
    """Rows emptied (or that would be, in a dry run) per kind."""

    dry_run: bool
    traces: int = 0
    trace_events: int = 0
    evaluations: int = 0
    judge_cache: int = 0
    feedback_reports: int = 0
    skipped: bool = False  # another worker holds the purge lock

    def total(self) -> int:
        return self.traces + self.trace_events + self.evaluations + self.judge_cache + self.feedback_reports

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ForgetRequest:
    document_ids: list[str] = field(default_factory=list)
    memory_item_ids: list[str] = field(default_factory=list)
    lineage_ids: list[str] = field(default_factory=list)  # ORBIT memory lineage (snapshot item keys)
    task_ids: list[str] = field(default_factory=list)  # NOVA task: observed runs ``external_id`` = «…:<task>»
    source: str = "api"
    reason: str = ""

    def count(self) -> int:
        return sum(map(len, (self.document_ids, self.memory_item_ids, self.lineage_ids, self.task_ids)))


@dataclass(slots=True)
class ForgetReceipt:
    """Acknowledgement of a forget request (what was matched and emptied)."""

    processed_at: datetime
    source: str
    runs: int = 0
    traces: int = 0
    trace_events: int = 0
    evaluations: int = 0
    scenario_versions: int = 0
    manifests: int = 0
    feedback_reports: int = 0
    judge_cache_entries: int = 0

    def total(self) -> int:
        return (
            self.runs + self.scenario_versions + self.manifests + self.feedback_reports
            + self.judge_cache_entries
        )  # fmt: skip


# =====================================================================================================
# Shared scrubbing
# =====================================================================================================


def scrub_feedback(row: FeedbackReport) -> bool:
    """Drop the quoted evidence of a report (error descriptions, examples, excerpts). ``True`` if changed."""
    errors = [{**e, "description": REDACTED_TEXT, "examples": [], "evidence": []} for e in row.errors or []]
    recommendations = [{**r, "evidence": []} for r in row.recommendations or []]
    if errors == list(row.errors or []) and recommendations == list(row.recommendations or []):
        return False
    row.errors, row.recommendations = errors, recommendations
    return True


def _has_json(column: Any) -> Any:
    """Column holds a value: neither SQL NULL nor the JSON ``null`` an ORM insert of ``None`` writes."""
    return and_(column.is_not(None), func.jsonb_typeof(column) != "null")


def _empty_trace(trace: ExecutionTrace, now: datetime) -> None:
    trace.input = {}
    trace.output_text = None
    trace.output_json = null()
    trace.messages = []
    trace.metadata_ = {**(trace.metadata_ or {}), "purged_at": now.isoformat()}


def _trace_needs_purge() -> Any:
    return and_(
        ExecutionTrace.metadata_["purged_at"].astext.is_(None),
        or_(
            ExecutionTrace.input != {},
            ExecutionTrace.output_text.is_not(None),
            _has_json(ExecutionTrace.output_json),
            ExecutionTrace.messages != [],
        ),
    )


# =====================================================================================================
# Scheduled retention
# =====================================================================================================


def _cutoff(days: int, now: datetime) -> datetime | None:
    return now - timedelta(days=days) if days > 0 else None


async def purge(
    session: AsyncSession,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
    actor: ActorLike = None,
    trigger: str = "schedule",
) -> PurgeReport:
    """Apply the retention rules. Flushes and records an audit entry; the caller commits."""
    now = now or utcnow()
    report = PurgeReport(dry_run=dry_run)
    if not await session.scalar(select(func.pg_try_advisory_xact_lock(PURGE_LOCK_KEY))):
        report.skipped = True
        return report

    trace_cutoff = _cutoff(settings.retention_trace_days, now)
    if trace_cutoff is not None:
        old_runs = select(EvaluationRun.id).where(EvaluationRun.finished_at < trace_cutoff)
        stale_traces = select(ExecutionTrace.id).where(
            ExecutionTrace.run_id.in_(old_runs), _trace_needs_purge()
        )
        report.traces = int(
            await session.scalar(select(func.count()).select_from(stale_traces.subquery())) or 0
        )
        event_filter = and_(
            TraceEvent.run_id.in_(old_runs),
            or_(_has_json(TraceEvent.input), _has_json(TraceEvent.output)),
        )
        report.trace_events = int(
            await session.scalar(select(func.count()).select_from(TraceEvent).where(event_filter)) or 0
        )
        if not dry_run:
            for trace in await session.scalars(
                select(ExecutionTrace).where(ExecutionTrace.id.in_(stale_traces))
            ):
                _empty_trace(trace, now)
            await session.execute(update(TraceEvent).where(event_filter).values(input=null(), output=null()))

    evaluation_cutoff = _cutoff(settings.retention_evaluation_days, now)
    if evaluation_cutoff is not None:
        filter_ = and_(
            Evaluation.run_id.in_(
                select(EvaluationRun.id).where(EvaluationRun.finished_at < evaluation_cutoff)
            ),
            _has_json(Evaluation.raw_response),
        )
        report.evaluations = int(
            await session.scalar(select(func.count()).select_from(Evaluation).where(filter_)) or 0
        )
        if not dry_run:
            await session.execute(update(Evaluation).where(filter_).values(raw_response=null()))

    cache_cutoff = _cutoff(settings.retention_judge_cache_days, now)
    if cache_cutoff is not None:
        report.judge_cache = int(
            await session.scalar(
                select(func.count())
                .select_from(JudgeCacheEntry)
                .where(JudgeCacheEntry.created_at < cache_cutoff)
            )
            or 0
        )
        if not dry_run:
            await session.execute(delete(JudgeCacheEntry).where(JudgeCacheEntry.created_at < cache_cutoff))

    feedback_cutoff = _cutoff(settings.retention_feedback_days, now)
    if feedback_cutoff is not None:
        rows = await session.scalars(
            select(FeedbackReport).where(FeedbackReport.created_at < feedback_cutoff)
        )
        for row in rows:
            report.feedback_reports += int(_would_scrub(row) if dry_run else scrub_feedback(row))

    if not dry_run:
        await session.flush()
        for kind, count in (
            ("trace", report.traces),
            ("trace_event", report.trace_events),
            ("evaluation", report.evaluations),
            ("judge_cache", report.judge_cache),
            ("feedback_report", report.feedback_reports),
        ):
            if count:
                RETENTION_PURGED_TOTAL.labels(kind=kind, trigger=trigger).inc(count)
    await audit.record(
        session,
        actor or Actor.system(),
        "retention.purge",
        "retention",
        summary=f"Rétention {'(simulation) ' if dry_run else ''}: {report.total()} élément(s)",
        details={**report.as_dict(), "trigger": trigger},
    )
    logger.info("Retention %s: %s", "dry run" if dry_run else "purge", report.as_dict())
    return report


def _would_scrub(row: FeedbackReport) -> bool:
    return any(
        e.get("examples") or e.get("evidence") or e.get("description") != REDACTED_TEXT
        for e in row.errors or []
    ) or any(r.get("evidence") for r in row.recommendations or [])


# =====================================================================================================
# Forgetting
# =====================================================================================================


def _clean(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in values if v and v.strip()))


def _fragments(request: ForgetRequest) -> list[dict[str, str]]:
    """JSON fragments a copied ORBIT document must contain to be concerned (``jsonb @>``)."""
    fragments = [{"document_id": v} for v in request.document_ids]
    fragments += [{"memory_item_id": v} for v in request.memory_item_ids]
    fragments += [{"id": v} for v in [*request.document_ids, *request.memory_item_ids]]
    fragments += [{"key": f"memory:{v}"} for v in request.lineage_ids]
    return fragments


def _matcher(request: ForgetRequest) -> Callable[[dict[str, Any]], bool]:
    documents, memories = set(request.document_ids), set(request.memory_item_ids)
    keys = {f"memory:{v}" for v in request.lineage_ids}

    def matches(doc: dict[str, Any]) -> bool:
        return bool(
            str(doc.get("document_id")) in documents
            or str(doc.get("memory_item_id")) in memories
            or str(doc.get("id")) in documents | memories
            or str(doc.get("key")) in keys
        )

    return matches


def _blank_documents(context: Any, matches: Callable[[dict[str, Any]], bool]) -> tuple[Any, int]:
    """Copy of ``context`` where matching documents lose their text (ids and levels are kept)."""
    if not isinstance(context, dict) or not isinstance(context.get("documents"), list):
        return context, 0
    count = 0
    documents: list[Any] = []
    for doc in context["documents"]:
        if isinstance(doc, dict) and matches(doc) and doc.get("content") != "":
            doc = {**doc, "title": FORGOTTEN_TEXT, "content": "", "forgotten": True}
            count += 1
        documents.append(doc)
    return ({**context, "documents": documents} if count else context), count


def _contains_any(column: Any, fragments: list[dict[str, str]]) -> Any:
    return or_(*(column.contains([f]) for f in fragments))


async def forget(session: AsyncSession, request: ForgetRequest, *, actor: ActorLike = None) -> ForgetReceipt:
    """Empty every copy of what ``request`` names. Idempotent; the caller commits."""
    request.document_ids = _clean(request.document_ids)
    request.memory_item_ids = _clean(request.memory_item_ids)
    request.lineage_ids = _clean(request.lineage_ids)
    request.task_ids = _clean(request.task_ids)
    if request.count() == 0:
        raise InvalidError("Indiquez au moins un identifiant à oublier")
    if request.count() > MAX_IDS:
        raise InvalidError(f"Trop d'identifiants ({MAX_IDS} au maximum par demande)")
    now = utcnow()
    receipt = ForgetReceipt(processed_at=now, source=request.source)
    fragments = _fragments(request)
    matches = _matcher(request)

    run_ids: set[Any] = set()
    touched: set[Any] = set()  # runs where something was actually emptied
    if fragments:
        run_ids |= set(
            await session.scalars(
                select(ExecutionTrace.run_id).where(
                    _contains_any(ExecutionTrace.input["context"]["documents"], fragments)
                )
            )
        )
        manifest_hits = (
            await session.scalars(
                select(EvaluationRun).where(
                    _contains_any(EvaluationRun.manifest["scenario"]["context"]["documents"], fragments)
                )
            )
        ).all()
        for run in manifest_hits:
            manifest, blanked = _blank_documents(
                ((run.manifest or {}).get("scenario") or {}).get("context"), matches
            )
            if blanked:
                run.manifest = {**run.manifest, "scenario": {**run.manifest["scenario"], "context": manifest}}
                touched.add(run.id)
                receipt.manifests += 1
            run_ids.add(run.id)
        for version in await session.scalars(
            select(ScenarioVersion).where(_contains_any(ScenarioVersion.context["documents"], fragments))
        ):
            context, blanked = _blank_documents(version.context, matches)
            if blanked:
                version.context = context
                receipt.scenario_versions += 1
    for task_id in request.task_ids:
        run_ids |= set(
            await session.scalars(
                select(EvaluationRun.id).where(
                    or_(EvaluationRun.external_id == task_id, EvaluationRun.external_id.like(f"%:{task_id}"))
                )
            )
        )

    if run_ids:
        for trace in await session.scalars(
            select(ExecutionTrace).where(ExecutionTrace.run_id.in_(run_ids), _trace_needs_purge())
        ):
            _empty_trace(trace, now)
            touched.add(trace.run_id)
            receipt.traces += 1
        events = await session.execute(
            update(TraceEvent)
            .where(
                TraceEvent.run_id.in_(run_ids),
                or_(_has_json(TraceEvent.input), _has_json(TraceEvent.output)),
            )
            .values(input=null(), output=null())
            .returning(TraceEvent.run_id)
        )
        emptied = events.scalars().all()
        touched |= set(emptied)
        receipt.trace_events = len(emptied)
        evaluations = await session.execute(
            update(Evaluation)
            .where(Evaluation.run_id.in_(run_ids), _has_json(Evaluation.raw_response))
            .values(raw_response=null())
            .returning(Evaluation.run_id)
        )
        emptied = evaluations.scalars().all()
        touched |= set(emptied)
        receipt.evaluations = len(emptied)
        for report in await session.scalars(select(FeedbackReport).where(FeedbackReport.run_id.in_(run_ids))):
            if scrub_feedback(report):
                touched.add(report.run_id)
                receipt.feedback_reports += 1
    receipt.runs = len(touched)

    if touched or receipt.scenario_versions:
        # The cache is keyed by hashes and not linked to runs: it is emptied as a whole (derivable data).
        deleted = await session.execute(delete(JudgeCacheEntry).returning(JudgeCacheEntry.key))
        receipt.judge_cache_entries = len(deleted.all())

    await session.flush()
    FORGET_REQUESTS_TOTAL.labels(source=request.source).inc()
    for kind, count in (
        ("trace", receipt.traces),
        ("trace_event", receipt.trace_events),
        ("evaluation", receipt.evaluations),
        ("scenario_version", receipt.scenario_versions),
        ("manifest", receipt.manifests),
        ("feedback_report", receipt.feedback_reports),
        ("judge_cache", receipt.judge_cache_entries),
    ):
        if count:
            RETENTION_PURGED_TOTAL.labels(kind=kind, trigger="forget").inc(count)
    await audit.record(
        session,
        actor or Actor.system(f"forget:{request.source}"),
        "forget.apply",
        "forget",
        summary=(
            f"Oubli appliqué ({request.source}) : {receipt.runs} run(s), "
            f"{receipt.scenario_versions} scénario(s)"
        ),
        details={
            "source": request.source,
            "reason": request.reason[:300],
            "document_ids": request.document_ids,
            "memory_item_ids": request.memory_item_ids,
            "lineage_ids": request.lineage_ids,
            "task_ids": request.task_ids,
            "receipt": {k: v for k, v in asdict(receipt).items() if k != "processed_at"},
        },
    )
    return receipt


__all__ = [
    "FORGOTTEN_TEXT",
    "ForgetReceipt",
    "ForgetRequest",
    "PurgeReport",
    "forget",
    "purge",
    "scrub_feedback",
]
