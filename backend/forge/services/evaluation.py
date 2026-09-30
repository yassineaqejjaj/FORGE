"""Evaluation Engine (owner: evaluation) — see docs/ARCHITECTURE.md §7. STUB: replaced by the module owner."""

from __future__ import annotations

from typing import Any


async def evaluate_run_job(session: Any, job: Any) -> None:
    raise NotImplementedError("Moteur d'évaluation non implémenté")


async def rescore_run(session: Any, run: Any, *, config: Any | None = None) -> Any:
    """Recompute scores + composite of the current round from stored evaluations (no judge call)."""
    raise NotImplementedError("Moteur d'évaluation non implémenté")
