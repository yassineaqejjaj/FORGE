"""Job kind → handler registry. Handlers live in the services of their module owner.

A handler is ``async def handler(session: AsyncSession, job: Job) -> None``. It commits its own
progress when useful; the worker commits the final state and marks the job. Raise
``forge.infra.queue.PermanentJobError`` for failures that retrying cannot fix and
``RetryableJobError`` for transient ones.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import Any

from forge.domain.enums import JobKind

Handler = Callable[[Any, Any], Awaitable[None]]

HANDLERS: dict[JobKind, str] = {
    JobKind.execute_run: "forge.services.execution:execute_run_job",
    JobKind.evaluate_run: "forge.services.evaluation:evaluate_run_job",
    JobKind.finalize_execution: "forge.services.benchmarks:finalize_execution_job",
    JobKind.finalize_experiment: "forge.services.experiments:finalize_experiment_job",
}


def resolve_handler(kind: JobKind) -> Handler:
    module_name, _, attr = HANDLERS[kind].partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)  # type: ignore[no-any-return]
