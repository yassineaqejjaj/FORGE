"""Wait for the seeded runs, benchmark executions and experiments to reach a terminal status.

* default: the compose workers (``runner-worker``, ``evaluation-worker``) process the queue and the
  seed polls the database;
* ``--sync``: the jobs are processed in-process with ``Worker.run_until_idle`` (both queues), which
  is what the tests do.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import func, or_, select

from forge.domain.enums import TERMINAL_RUN_STATUSES, ExecutionStatus, RunStatus
from forge.infra.db import get_sessionmaker
from forge.infra.models import BenchmarkExecution, EvaluationRun, Experiment

logger = logging.getLogger("forge.seed")

TERMINAL_GROUP_STATUSES = frozenset(
    {ExecutionStatus.completed, ExecutionStatus.failed, ExecutionStatus.cancelled}
)
POLL_SECONDS = 3.0


class SeedTimeout(RuntimeError):
    """The pipeline did not finish within the allotted time."""


@dataclass(slots=True)
class Tracked:
    """What the seed waits for."""

    execution_ids: list[uuid.UUID] = field(default_factory=list)
    experiment_ids: list[uuid.UUID] = field(default_factory=list)
    run_ids: list[uuid.UUID] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.execution_ids or self.experiment_ids or self.run_ids)


@dataclass(slots=True)
class Progress:
    total: int
    by_status: dict[str, int]
    groups_pending: int

    @property
    def terminal(self) -> int:
        return sum(n for s, n in self.by_status.items() if RunStatus(s) in TERMINAL_RUN_STATUSES)

    @property
    def done(self) -> bool:
        return self.terminal >= self.total and self.groups_pending == 0

    def describe(self) -> str:
        parts = [f"{self.terminal}/{self.total} runs terminés"]
        for status in (RunStatus.pending, RunStatus.running, RunStatus.evaluating, RunStatus.failed):
            if self.by_status.get(status.value):
                parts.append(f"{status.value} {self.by_status[status.value]}")
        if self.groups_pending:
            parts.append(f"{self.groups_pending} agrégation(s) en attente")
        return ", ".join(parts)


async def progress(tracked: Tracked) -> Progress:
    conditions = []
    if tracked.execution_ids:
        conditions.append(EvaluationRun.benchmark_execution_id.in_(tracked.execution_ids))
    if tracked.experiment_ids:
        conditions.append(EvaluationRun.experiment_id.in_(tracked.experiment_ids))
    if tracked.run_ids:
        conditions.append(EvaluationRun.id.in_(tracked.run_ids))
    async with get_sessionmaker()() as session:
        by_status: dict[str, int] = {}
        if conditions:
            rows = await session.execute(
                select(EvaluationRun.status, func.count())
                .where(or_(*conditions))
                .group_by(EvaluationRun.status)
            )
            by_status = {str(RunStatus(status).value): int(count) for status, count in rows.all()}
        pending = 0
        if tracked.execution_ids:
            pending += int(
                await session.scalar(
                    select(func.count())
                    .select_from(BenchmarkExecution)
                    .where(
                        BenchmarkExecution.id.in_(tracked.execution_ids),
                        BenchmarkExecution.status.not_in(list(TERMINAL_GROUP_STATUSES)),
                    )
                )
                or 0
            )
        if tracked.experiment_ids:
            pending += int(
                await session.scalar(
                    select(func.count())
                    .select_from(Experiment)
                    .where(
                        Experiment.id.in_(tracked.experiment_ids),
                        Experiment.status.not_in(list(TERMINAL_GROUP_STATUSES)),
                    )
                )
                or 0
            )
    return Progress(total=sum(by_status.values()), by_status=by_status, groups_pending=pending)


async def wait_for(
    tracked: Tracked,
    *,
    sync: bool,
    limit_seconds: float,
    label: str,
    log: Callable[[str], None],
) -> Progress:
    """Block until everything tracked is terminal (raises :class:`SeedTimeout`)."""
    started = time.monotonic()
    worker = _worker() if sync else None
    last = ""
    while True:
        processed = 0
        if worker is not None:
            processed = await worker.run_until_idle()
        state = await progress(tracked)
        text = state.describe()
        if text != last:
            log(f"  [{label}] {text}")
            last = text
        if state.done:
            return state
        if time.monotonic() - started > limit_seconds:
            raise SeedTimeout(
                f"{label} : délai de {limit_seconds:.0f} s dépassé ({text}). Les workers tournent-ils "
                "(`docker compose ps`) ? Relancez `make seed` pour reprendre, ou utilisez --sync."
            )
        if worker is None or processed == 0:
            await asyncio.sleep(POLL_SECONDS if worker is None else 0.2)


class _InProcessWorker(Protocol):
    async def run_until_idle(self, *, max_jobs: int = ...) -> int: ...


def _worker() -> _InProcessWorker:
    """``forge.workers.worker.Worker`` on both queues.

    ``forge.seed`` and ``forge.workers`` are sibling layers that must not import each other
    statically (import-linter): ``--sync`` borrows the worker at run time only, exactly like the
    tests do, so that the jobs follow the real pipeline (same handlers, retries, failure handling).
    """
    module = importlib.import_module("forge.workers.worker")
    worker: _InProcessWorker = module.Worker(
        queues=["execution", "evaluation"], concurrency=1, worker_id="forge-seed"
    )
    return worker
