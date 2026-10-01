"""Postgres job queue (``jobs``) with ``SELECT … FOR UPDATE SKIP LOCKED`` — docs/ARCHITECTURE.md §8.

Lifecycle: ``queued`` → (claimed) ``running`` → ``succeeded`` | ``failed`` | ``cancelled``. A failed
attempt is re-queued with exponential backoff until ``max_attempts``.

Transaction rules:

* :func:`enqueue_job`, :func:`mark_succeeded`, :func:`mark_failed` only flush — the caller commits
  (an enqueue is atomic with the state change that motivates it);
* :func:`claim_next_job` and :func:`requeue_stale_jobs` commit themselves (short row locks).

Handlers raise :class:`PermanentJobError` for failures that retrying cannot fix.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import JOB_QUEUES, JobKind, JobQueue, JobStatus
from forge.infra.db import utcnow
from forge.infra.models import Job
from forge.infra.observability.metrics import record_job

BACKOFF_BASE_SECONDS = 5.0
BACKOFF_MAX_SECONDS = 600.0
MAX_ERROR_LENGTH = 4000

#: Priorities (higher first).
PRIORITY_INTERACTIVE = 100  # single runs launched from the UI / API
PRIORITY_EXPERIMENT = 50
PRIORITY_BENCHMARK = 10
PRIORITY_FINALIZE = 200  # aggregation jobs are cheap: never starve them


class JobError(Exception):
    """Base class for job failures raised by handlers."""


class PermanentJobError(JobError):
    """Failure that retrying cannot fix: the job is marked ``failed`` immediately."""


class RetryableJobError(JobError):
    """Transient failure (dependency unavailable, rate limited…): retried with backoff."""

    def __init__(self, message: str, *, delay_seconds: float | None = None) -> None:
        super().__init__(message)
        self.delay_seconds = delay_seconds


def backoff_delay(attempt: int, *, jitter: bool = True) -> float:
    """Seconds before retry ``attempt`` (1-based): 5 s, 10 s, 20 s … capped at 10 min."""
    delay = min(BACKOFF_MAX_SECONDS, BACKOFF_BASE_SECONDS * (2 ** max(0, attempt - 1)))
    if jitter:
        delay *= random.uniform(0.85, 1.15)
    return delay


async def enqueue_job(
    session: AsyncSession,
    kind: JobKind | str,
    *,
    run_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    priority: int = 0,
    run_after: datetime | None = None,
    max_attempts: int = 3,
    dedupe_key: str | None = None,
) -> Job | None:
    """Add a ``queued`` job (flushed; caller commits).

    With ``dedupe_key``, nothing is inserted when an active (queued/running) job with the same key
    exists; ``None`` is returned in that case.
    """
    job_kind = JobKind(kind)
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "kind": job_kind,
        "queue": JOB_QUEUES[job_kind],
        "status": JobStatus.queued,
        "priority": priority,
        "attempts": 0,
        "max_attempts": max(1, max_attempts),
        "payload": dict(payload or {}),
        "run_id": run_id,
        "dedupe_key": dedupe_key,
        "run_after": run_after or utcnow(),
        "created_at": utcnow(),
    }
    if dedupe_key is None:
        job = Job(**values)
        session.add(job)
        await session.flush()
        return job
    stmt = (
        insert(Job)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["dedupe_key"],
            # Literal predicate: must match the partial index exactly (bound parameters would not).
            index_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
        )
        .returning(Job.id)
    )
    inserted = (await session.execute(stmt)).scalar_one_or_none()
    if inserted is None:
        return None
    return await session.get(Job, inserted)


async def claim_next_job(
    session: AsyncSession,
    worker_id: str,
    queues: Sequence[JobQueue | str],
) -> Job | None:
    """Atomically claim the highest-priority runnable job of ``queues`` (commits)."""
    now = utcnow()
    stmt = (
        select(Job)
        .where(
            Job.status == JobStatus.queued,
            Job.run_after <= now,
            Job.queue.in_([JobQueue(q) for q in queues]),
        )
        .order_by(Job.priority.desc(), Job.run_after, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = await session.scalar(stmt)
    if job is None:
        await session.rollback()
        return None
    job.status = JobStatus.running
    job.attempts = job.attempts + 1
    job.locked_by = worker_id
    job.locked_at = now
    job.started_at = now
    job.finished_at = None
    await session.commit()
    return job


async def mark_succeeded(session: AsyncSession, job: Job) -> None:
    job.status = JobStatus.succeeded
    job.finished_at = utcnow()
    job.locked_by = None
    job.locked_at = None
    job.error = None
    await session.flush()
    record_job(job.kind.value, "succeeded")


async def mark_failed(
    session: AsyncSession,
    job: Job,
    error: str | BaseException,
    *,
    retryable: bool = True,
    delay_seconds: float | None = None,
) -> bool:
    """Record a failed attempt. Returns ``True`` when the job was re-queued for a retry."""
    message = _error_message(error)
    job.error = message[:MAX_ERROR_LENGTH]
    job.locked_by = None
    job.locked_at = None
    if retryable and job.attempts < job.max_attempts:
        job.status = JobStatus.queued
        delay = delay_seconds if delay_seconds is not None else backoff_delay(job.attempts)
        job.run_after = utcnow() + timedelta(seconds=delay)
        await session.flush()
        record_job(job.kind.value, "retried")
        return True
    job.status = JobStatus.failed
    job.finished_at = utcnow()
    await session.flush()
    record_job(job.kind.value, "failed")
    return False


async def cancel_jobs_for_runs(session: AsyncSession, run_ids: Sequence[uuid.UUID]) -> int:
    """Cancel queued jobs of the given runs (flush only). Running jobs finish their current step."""
    if not run_ids:
        return 0
    result = await session.execute(
        update(Job)
        .where(Job.run_id.in_(list(run_ids)), Job.status == JobStatus.queued)
        .values(status=JobStatus.cancelled, finished_at=utcnow())
        .returning(Job.id)
    )
    return len(result.all())


def _error_message(error: str | BaseException) -> str:
    if isinstance(error, BaseException):
        text = str(error).strip()
        return text or type(error).__name__
    return str(error)


async def requeue_stale_jobs(session: AsyncSession, older_than_seconds: float) -> int:
    """Re-queue ``running`` jobs whose lock is older than the threshold (crashed worker). Commits."""
    threshold = utcnow() - timedelta(seconds=older_than_seconds)
    result = await session.execute(
        update(Job)
        .where(Job.status == JobStatus.running, Job.locked_at < threshold)
        .values(
            status=JobStatus.queued,
            locked_by=None,
            locked_at=None,
            run_after=utcnow(),
            error="Traitement interrompu (worker arrêté) — relancé automatiquement",
        )
        .returning(Job.id)
    )
    count = len(result.all())
    await session.commit()
    return count


async def queue_depth(session: AsyncSession) -> dict[str, int]:
    """Number of queued jobs per queue (exposed on /ready and the dashboard)."""
    from sqlalchemy import func

    rows = await session.execute(
        select(Job.queue, func.count()).where(Job.status == JobStatus.queued).group_by(Job.queue)
    )
    depth = {q.value: 0 for q in JobQueue}
    for queue, count in rows.all():
        depth[JobQueue(queue).value] = int(count)
    return depth
