"""FORGE worker: processes the Postgres job queue (``python -m forge.workers``).

* ``FORGE_WORKER_QUEUES`` selects the queues (``execution`` = agent calls, ``evaluation`` =
  rules, judges, aggregation). Deploy them as separate services to scale independently;
* ``FORGE_WORKER_CONCURRENCY`` slots claim jobs with ``SELECT … FOR UPDATE SKIP LOCKED``;
* failures are retried with exponential backoff; stale ``running`` jobs are re-queued;
* SIGTERM/SIGINT: stop claiming, let in-flight jobs finish within the grace period.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
import uuid
from dataclasses import dataclass, field

from forge.config import settings
from forge.domain.enums import JobQueue, JobStatus
from forge.infra import cache
from forge.infra.db import dispose_engine, get_sessionmaker, utcnow
from forge.infra.models import Job
from forge.infra.observability.logging_setup import setup_logging
from forge.infra.observability.metrics import WORKER_INFLIGHT
from forge.infra.observability.tracing import get_tracer, setup_tracing, shutdown_tracing
from forge.infra.queue import (
    PermanentJobError,
    RetryableJobError,
    claim_next_job,
    mark_failed,
    mark_succeeded,
    requeue_stale_jobs,
)
from forge.workers.handlers import resolve_handler

logger = logging.getLogger("forge.worker")

STALE_CHECK_INTERVAL_SECONDS = 60.0
ERROR_BACKOFF_SECONDS = 5.0


@dataclass
class WorkerStats:
    started_at: float = field(default_factory=time.monotonic)
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    in_flight: int = 0


class Worker:
    def __init__(
        self,
        queues: list[str] | None = None,
        concurrency: int | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.queues = [JobQueue(q) for q in (queues or settings.queues)]
        self.concurrency = concurrency or settings.worker_concurrency
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
        self.stop_event = asyncio.Event()
        self.stats = WorkerStats()
        self._tracer = get_tracer("forge.worker")
        self._queue_label = ",".join(q.value for q in self.queues)

    def request_stop(self) -> None:
        if not self.stop_event.is_set():
            logger.info(
                "Shutdown requested: finishing in-flight jobs (grace %.0fs)",
                settings.worker_shutdown_grace_seconds,
            )
            self.stop_event.set()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)

    async def run(self) -> None:
        logger.info(
            "Worker %s starting (queues=%s, concurrency=%d)",
            self.worker_id,
            self._queue_label,
            self.concurrency,
        )
        slots = [asyncio.create_task(self._slot(i), name=f"slot-{i}") for i in range(self.concurrency)]
        background = [
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
            asyncio.create_task(self._stale_requeue_loop(), name="stale-requeue"),
        ]
        await self.stop_event.wait()
        _done, pending = await asyncio.wait(slots, timeout=settings.worker_shutdown_grace_seconds)
        for task in pending:
            task.cancel()
        for task in background:
            task.cancel()
        await asyncio.gather(*pending, *background, return_exceptions=True)
        logger.info(
            "Worker %s stopped (succeeded=%d failed=%d retried=%d)",
            self.worker_id, self.stats.succeeded, self.stats.failed, self.stats.retried,
        )  # fmt: skip

    async def run_until_idle(self, *, max_jobs: int = 10_000) -> int:
        """Process jobs sequentially until the queues are empty (tests, CLI ``--sync``)."""
        processed = 0
        while processed < max_jobs:
            async with get_sessionmaker()() as session:
                job = await claim_next_job(session, self.worker_id, self.queues)
            if job is None:
                return processed
            await self._process(job.id)
            processed += 1
        return processed

    async def _slot(self, index: int) -> None:
        while not self.stop_event.is_set():
            try:
                async with get_sessionmaker()() as session:
                    job = await claim_next_job(session, self.worker_id, self.queues)
            except Exception:
                logger.exception("Slot %d: unable to claim a job (database unavailable?)", index)
                await self._sleep(ERROR_BACKOFF_SECONDS)
                continue
            if job is None:
                await self._sleep(settings.worker_poll_interval_seconds)
                continue
            await self._process(job.id)

    async def _process(self, job_id: uuid.UUID) -> None:
        self.stats.in_flight += 1
        gauge = WORKER_INFLIGHT.labels(queue=self._queue_label)
        gauge.inc()
        started = time.perf_counter()
        try:
            async with get_sessionmaker()() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    return
                label = f"{job.kind} job={job.id} run={job.run_id} attempt={job.attempts}/{job.max_attempts}"
                logger.info("Running %s", label)
                with self._tracer.start_as_current_span(f"job.{job.kind}") as span:
                    span.set_attribute("forge.job_id", str(job.id))
                    if job.run_id:
                        span.set_attribute("forge.run_id", str(job.run_id))
                    span.set_attribute("forge.attempt", job.attempts)
                    try:
                        handler = resolve_handler(job.kind)
                        await asyncio.wait_for(
                            handler(session, job), timeout=settings.worker_job_timeout_seconds
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        span.record_exception(exc)
                        await session.rollback()
                        await self._fail(job_id, exc)
                        return
                    job = await session.get(Job, job_id)
                    if job is not None and job.status == JobStatus.running:
                        await mark_succeeded(session, job)
                    await session.commit()
                    self.stats.succeeded += 1
                    logger.info("Succeeded %s in %.0f ms", label, (time.perf_counter() - started) * 1000)
        except asyncio.CancelledError:
            logger.warning("Job %s interrupted by shutdown: re-queued", job_id)
            with contextlib.suppress(Exception):
                await asyncio.shield(self._requeue_interrupted(job_id))
            raise
        except Exception:
            logger.exception("Unexpected error while finalising job %s", job_id)
            with contextlib.suppress(Exception):
                await self._fail(job_id, RuntimeError("Erreur interne du worker"))
        finally:
            self.stats.in_flight -= 1
            gauge.dec()

    async def _requeue_interrupted(self, job_id: uuid.UUID) -> None:
        async with get_sessionmaker()() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status != JobStatus.running:
                return
            job.status = JobStatus.queued
            job.attempts = max(0, job.attempts - 1)
            job.locked_by = None
            job.locked_at = None
            job.run_after = utcnow()
            await session.commit()

    async def _fail(self, job_id: uuid.UUID, exc: BaseException) -> None:
        delay: float | None = None
        if isinstance(exc, TimeoutError):
            error: BaseException = RuntimeError(
                f"Délai de traitement dépassé ({settings.worker_job_timeout_seconds:.0f} s)"
            )
            retryable = True
        elif isinstance(exc, NotImplementedError):
            error = RuntimeError(str(exc) or "Traitement non disponible sur cette instance")
            retryable = False
        elif isinstance(exc, RetryableJobError):
            error, retryable, delay = exc, True, exc.delay_seconds
        else:
            error = exc
            retryable = not isinstance(exc, PermanentJobError)
        async with get_sessionmaker()() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            will_retry = await mark_failed(session, job, error, retryable=retryable, delay_seconds=delay)
            if not will_retry:
                await _on_job_exhausted(session, job, error)
            await session.commit()
        if will_retry:
            self.stats.retried += 1
            logger.warning(
                "Job %s failed (attempt %d/%d), retry scheduled: %s",
                job_id,
                job.attempts,
                job.max_attempts,
                error,
            )
        else:
            self.stats.failed += 1
            logger.error("Job %s failed permanently: %s", job_id, error)

    async def _heartbeat(self) -> None:
        while not self.stop_event.is_set():
            await self._sleep(settings.worker_heartbeat_seconds)
            if self.stop_event.is_set():
                break
            logger.info(
                "heartbeat worker=%s queues=%s uptime=%.0fs in_flight=%d succeeded=%d failed=%d retried=%d",
                self.worker_id, self._queue_label, time.monotonic() - self.stats.started_at,
                self.stats.in_flight, self.stats.succeeded, self.stats.failed, self.stats.retried,
            )  # fmt: skip

    async def _stale_requeue_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                async with get_sessionmaker()() as session:
                    count = await requeue_stale_jobs(session, settings.worker_stale_lock_seconds)
                if count:
                    logger.warning("Re-queued %d stale job(s)", count)
            except Exception as exc:
                logger.warning("Stale job check failed: %s", exc)
            await self._sleep(STALE_CHECK_INTERVAL_SECONDS)


async def _on_job_exhausted(session: object, job: Job, error: BaseException) -> None:
    """A run job failed for good: the run itself must not stay stuck in a non-terminal status."""
    if job.run_id is None:
        return
    from forge.domain.enums import TERMINAL_RUN_STATUSES
    from forge.infra.models import EvaluationRun
    from forge.services import runs as run_service

    run = await session.get(EvaluationRun, job.run_id)  # type: ignore[attr-defined]
    if run is None or run.status in TERMINAL_RUN_STATUSES:
        return
    await run_service.mark_failed(session, run, f"Échec du traitement ({job.kind}) : {error}")  # type: ignore[arg-type]


def _start_metrics_server() -> None:
    if settings.worker_metrics_port <= 0:
        return
    try:
        from prometheus_client import start_http_server

        start_http_server(settings.worker_metrics_port)
        logger.info("Worker metrics exposed on :%d/metrics", settings.worker_metrics_port)
    except OSError as exc:
        logger.warning("Worker metrics endpoint disabled: %s", exc)


async def main() -> None:
    setup_logging(settings.log_level)
    setup_tracing("forge-worker")
    _start_metrics_server()
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)
    try:
        await worker.run()
    finally:
        await cache.close_valkey()
        await dispose_engine()
        shutdown_tracing()
