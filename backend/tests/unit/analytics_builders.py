"""Builders of ``RunSummary`` objects for the analytics unit tests (pure, no database)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from forge.domain.enums import ExperimentArm, ScenarioVisibility
from forge.domain.types import RunSummary

_NAMESPACE = uuid.UUID("5b6f0e3e-0000-4000-8000-000000000000")


def sid(name: str) -> str:
    """Deterministic id from a readable name."""
    return str(uuid.uuid5(_NAMESPACE, name))


def make_run(
    *,
    scenario: str = "s1",
    agent: str = "A",
    version: str = "1.0",
    composite: float | None = 80.0,
    repetition: int = 0,
    status: str = "completed",
    passed: bool | None = None,
    gate_failed: bool = False,
    dimensions: dict[str, float] | None = None,
    errors: list[tuple[str, str]] | None = None,
    cost: float | None = 0.01,
    latency_ms: float | None = 1000.0,
    tokens: int | None = 1000,
    family: str | None = None,
    category: str = "product_management",
    difficulty: str = "medium",
    visibility: ScenarioVisibility = ScenarioVisibility.public,
    model: str | None = "gpt-test",
    arm: ExperimentArm | None = None,
    created_at: datetime | None = None,
    **extra: Any,
) -> RunSummary:
    if passed is None:
        passed = composite is not None and composite >= 70 and not gate_failed
    return RunSummary(
        run_id=str(uuid.uuid4()),
        scenario_id=sid(f"scenario:{scenario}"),
        scenario_version_id=sid(f"scenario-version:{scenario}"),
        scenario_slug=scenario,
        scenario_name=f"Scénario {scenario}",
        family_id=sid(f"scenario:{family or scenario}"),
        category=category,
        difficulty=difficulty,
        visibility=visibility,
        agent_id=sid(f"agent:{agent}"),
        agent_version_id=sid(f"agent-version:{agent}:{version}"),
        agent_label=f"{agent} v{version}",
        model=model,
        repetition=repetition,
        status=status,
        composite=composite,
        passed=passed,
        gate_failed=gate_failed,
        dimensions=dimensions
        if dimensions is not None
        else ({} if composite is None else {"quality": composite / 100}),
        criteria={},
        cost=cost,
        latency_ms=latency_ms,
        tokens=tokens,
        errors=list(errors or []),
        arm=arm,
        created_at=created_at or datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        **extra,
    )
