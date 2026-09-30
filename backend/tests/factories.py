"""Database factories shared by every test module (they bypass the API on purpose).

They let each module be tested in isolation: evaluation tests start from an executed run
(:func:`attach_trace`), analytics tests from scored runs (:func:`complete_with_scores`).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import (
    AdapterKind,
    Difficulty,
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    EventStatus,
    RunOrigin,
    RunStatus,
    ScenarioVisibility,
    ScoreSource,
    TraceEventSource,
    TraceEventType,
)
from forge.domain.versioning import agent_version_hash, new_canary, scenario_version_hash
from forge.infra.db import utcnow
from forge.infra.models import (
    Agent,
    AgentVersion,
    CompositeScore,
    EvaluationConfig,
    EvaluationRun,
    ExecutionTrace,
    RunError,
    Scenario,
    ScenarioVersion,
    Score,
    TraceEvent,
)
from forge.services.runs import RunPlan, create_runs


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


async def create_agent_version(
    session: AsyncSession,
    *,
    agent: Agent | None = None,
    name: str = "Agent de test",
    version: str = "1.0",
    adapter_kind: AdapterKind = AdapterKind.mock,
    endpoint: str | None = None,
    system_prompt: str = "Tu es un agent de test.",
    adapter_config: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> AgentVersion:
    if agent is None:
        agent = Agent(slug=uid("agent"), name=name, provider="Tests")
        session.add(agent)
        await session.flush()
    count = len(list(await session.scalars(select(AgentVersion.id).where(AgentVersion.agent_id == agent.id))))
    fields: dict[str, Any] = {
        "adapter_kind": adapter_kind.value,
        "endpoint": endpoint,
        "model": None,
        "system_prompt": system_prompt,
        "tools": [],
        "context_config": {},
        "memory_config": {},
        "orchestration_config": {},
        "adapter_config": adapter_config or {},
        "budget": budget or {},
        "credential_id": None,
    }
    av = AgentVersion(
        agent_id=agent.id,
        version=version,
        version_number=count + 1,
        adapter_kind=adapter_kind,
        endpoint=endpoint,
        system_prompt=system_prompt,
        adapter_config=adapter_config or {},
        budget=budget or {},
        content_hash=agent_version_hash(**fields),
    )
    session.add(av)
    await session.flush()
    return av


async def create_scenario_version(
    session: AsyncSession,
    *,
    scenario: Scenario | None = None,
    name: str = "Scénario de test",
    category: str = "product_management",
    visibility: ScenarioVisibility = ScenarioVisibility.public,
    prompt: str = "Rédige un PRD pour la fonctionnalité d'export CSV.",
    context: dict[str, Any] | None = None,
    constraints: list[str] | None = None,
    expected_output: Any = "Un PRD avec objectifs, périmètre, exigences, critères d'acceptation.",
    expected_behavior: str = "",
    criteria: list[dict[str, Any]] | None = None,
    rules: list[dict[str, Any]] | None = None,
    tool_mocks: list[dict[str, Any]] | None = None,
    difficulty: Difficulty = Difficulty.medium,
    parent: Scenario | None = None,
    variant_label: str | None = None,
) -> ScenarioVersion:
    if scenario is None:
        scenario_id = uuid.uuid4()
        scenario = Scenario(
            id=scenario_id,
            slug=uid("scenario"),
            name=name,
            category=category,
            visibility=visibility,
            parent_scenario_id=parent.id if parent else None,
            family_id=parent.family_id if parent else scenario_id,
            variant_label=variant_label,
        )
        session.add(scenario)
        await session.flush()
        version_number = 1
    else:
        scenario.latest_version += 1
        version_number = scenario.latest_version
    fields: dict[str, Any] = {
        "description": "",
        "difficulty": difficulty.value,
        "input": {"prompt": prompt},
        "context": context or {},
        "constraints": constraints or [],
        "expected_output": expected_output,
        "expected_behavior": expected_behavior,
        "criteria": criteria or [],
        "rules": rules or [],
        "tool_mocks": tool_mocks or [],
        "dataset_id": None,
    }
    sv = ScenarioVersion(
        scenario_id=scenario.id,
        version=version_number,
        difficulty=difficulty,
        input=fields["input"],
        context=fields["context"],
        constraints=fields["constraints"],
        expected_output=expected_output,
        expected_behavior=expected_behavior,
        criteria=fields["criteria"],
        rules=fields["rules"],
        tool_mocks=fields["tool_mocks"],
        canary=new_canary(),
        content_hash=scenario_version_hash(**fields),
    )
    session.add(sv)
    await session.flush()
    return sv


async def default_config(session: AsyncSession) -> EvaluationConfig:
    config = await session.scalar(
        select(EvaluationConfig).where(
            EvaluationConfig.is_default.is_(True), EvaluationConfig.is_latest.is_(True)
        )
    )
    assert config is not None, "bootstrap data missing (use the `app` fixture)"
    return config


async def create_run(
    session: AsyncSession,
    sv: ScenarioVersion,
    av: AgentVersion,
    *,
    config: EvaluationConfig | None = None,
    origin: RunOrigin = RunOrigin.adhoc,
    repetition: int = 0,
    enqueue: bool = False,
    **kwargs: Any,
) -> EvaluationRun:
    config = config or await default_config(session)
    (run,) = await create_runs(
        session,
        [
            RunPlan(
                scenario_version_id=sv.id,
                agent_version_id=av.id,
                repetition=repetition,
                arm=kwargs.pop("arm", None),
            )
        ],
        evaluation_config=config,
        origin=origin,
        enqueue=enqueue,
        **kwargs,
    )
    return run


async def attach_trace(
    session: AsyncSession,
    run: EvaluationRun,
    *,
    output_text: str,
    output_json: Any = None,
    events: list[dict[str, Any]] | None = None,
    input_tokens: int = 1200,
    output_tokens: int = 600,
    cost: float = 0.012,
    latency_ms: float = 3200.0,
) -> ExecutionTrace:
    """Simulate a finished execution: trace + events, run left in EVALUATING (no job enqueued).

    ``events`` items: ``{"type", "name", "input"?, "output"?, "attributes"?, "status"?, "offset_ms"?,
    "duration_ms"?}`` — ``run_started`` and ``final_answer`` are added automatically.
    """
    started = utcnow() - timedelta(milliseconds=latency_ms)
    items = [{"type": TraceEventType.run_started, "name": "Scénario démarré", "offset_ms": 0.0}]
    items += events or []
    items.append(
        {
            "type": TraceEventType.final_answer,
            "name": "Réponse finale",
            "output": output_text,
            "offset_ms": latency_ms,
        }
    )
    for seq, item in enumerate(items, start=1):
        offset = float(item.get("offset_ms", seq * 100.0))
        duration = item.get("duration_ms")
        session.add(
            TraceEvent(
                run_id=run.id,
                seq=seq,
                type=TraceEventType(item["type"]),
                name=item["name"],
                source=TraceEventSource.runner,
                status=EventStatus(item.get("status", "ok")),
                started_at=started + timedelta(milliseconds=offset),
                ended_at=started + timedelta(milliseconds=offset + (duration or 0)),
                offset_ms=offset,
                duration_ms=duration,
                input=item.get("input"),
                output=item.get("output"),
                attributes=item.get("attributes", {}),
            )
        )
    trace = ExecutionTrace(
        run_id=run.id,
        started_at=started,
        completed_at=utcnow(),
        total_latency_ms=latency_ms,
        input={"input": run.manifest["scenario"]["input"]},
        output_text=output_text,
        output_json=output_json,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost=cost,
        model_calls=1,
        tool_calls=sum(1 for i in items if i["type"] == TraceEventType.tool_call),
        event_count=len(items),
    )
    session.add(trace)
    run.status = RunStatus.evaluating
    run.started_at = started
    run.executed_at = utcnow()
    await session.flush()
    return trace


async def complete_with_scores(
    session: AsyncSession,
    run: EvaluationRun,
    *,
    composite: float,
    dimensions: dict[str, float] | None = None,
    errors: list[tuple[str, str]] | None = None,
    gate_failed: bool = False,
    cost: float = 0.012,
    latency_ms: float = 3200.0,
) -> EvaluationRun:
    """Simulate a fully evaluated run (analytics tests): trace, scores, composite, errors."""
    if await session.scalar(select(ExecutionTrace.id).where(ExecutionTrace.run_id == run.id)) is None:
        await attach_trace(session, run, output_text="Sortie simulée", cost=cost, latency_ms=latency_ms)
    run.evaluation_round = 1
    dims = dimensions or {"quality": composite / 100, "safety": 1.0}
    for dim, value in dims.items():
        session.add(
            Score(
                run_id=run.id,
                round=1,
                evaluation_config_id=run.evaluation_config_id,
                criterion_key=f"{dim}.synthetic",
                dimension=Dimension(dim),
                value=value,
                weight=1.0,
                source=ScoreSource.ai,
                confidence=0.9,
                explanation="Score synthétique de test",
                method="single_judge",
            )
        )
    session.add(
        CompositeScore(
            run_id=run.id,
            round=1,
            evaluation_config_id=run.evaluation_config_id,
            value=0.0 if gate_failed else composite,
            raw_value=composite,
            passed=(not gate_failed) and composite >= 70,
            gate_failed=gate_failed,
            dimensions=[
                {"dimension": d, "value": v, "weight": 1.0, "effective_weight": 1 / len(dims), "criteria": []}
                for d, v in dims.items()
            ],
            gates=[],
            missing_dimensions=[],
            formula="synthétique",
        )
    )
    for error_type, severity in errors or []:
        session.add(
            RunError(
                run_id=run.id,
                round=1,
                error_type=error_type,
                severity=ErrorSeverity(severity),
                description=f"Erreur {error_type} simulée",
                evaluator_kind=EvaluatorKind.llm_judge,
                evaluator_key="test-judge@v1",
            )
        )
    run.composite_score = 0.0 if gate_failed else composite
    run.gate_failed = gate_failed
    run.passed = (not gate_failed) and composite >= 70
    run.status = RunStatus.completed
    run.finished_at = utcnow()
    run.evaluated_at = run.finished_at
    await session.flush()
    return run
