"""Ports (interfaces) of the FORGE domain — docs/ARCHITECTURE.md §5.2.

Adding an agent provider = implementing :class:`AgentAdapter` and registering it in
``forge.adapters.registry``. Adding an evaluator = implementing :class:`Evaluator` and registering
it in ``forge.domain.evaluators_registry``. Adding an LLM provider for judges = implementing
:class:`LLMClient` in ``forge.infra.llm``.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from forge.domain.enums import AdapterKind, EvaluatorKind, EventStatus, TraceEventType
from forge.domain.types import (
    AgentRequest,
    AgentResult,
    EvaluationContext,
    EvaluationResult,
    TokenUsage,
    TraceEventData,
)


class EventHandle(Protocol):
    """Mutable handle on an event being recorded (returned by :meth:`TraceRecorder.span`)."""

    @property
    def key(self) -> str: ...

    def set_output(self, output: Any) -> None: ...

    def set_attributes(self, **attributes: Any) -> None: ...

    def fail(self, message: str, *, error_type: str | None = None) -> None: ...


@runtime_checkable
class TraceRecorder(Protocol):
    """Collects the execution trace of one run (implemented by ``forge.domain.traces.recorder``)."""

    def event(
        self,
        type: TraceEventType,
        name: str,
        *,
        input: Any = None,
        output: Any = None,
        attributes: dict[str, Any] | None = None,
        status: EventStatus = EventStatus.ok,
        parent: str | None = None,
        duration_ms: float | None = None,
    ) -> str:
        """Record an instantaneous (or already finished) event; returns its key."""
        ...

    def span(
        self,
        type: TraceEventType,
        name: str,
        *,
        input: Any = None,
        attributes: dict[str, Any] | None = None,
        parent: str | None = None,
    ) -> AbstractContextManager[EventHandle]:
        """Context manager timing an event; exceptions mark it ``error`` and propagate."""
        ...

    def add_usage(self, usage: TokenUsage, *, cost: float | None = None, model_call: bool = True) -> None: ...

    def count_tool_call(self) -> None: ...

    @property
    def events(self) -> Sequence[TraceEventData]: ...


@runtime_checkable
class AgentAdapter(Protocol):
    """Executes one scenario against one agent version and reports what happened."""

    kind: AdapterKind

    async def invoke(self, request: AgentRequest, recorder: TraceRecorder) -> AgentResult:
        """Run the agent. Raise ``AgentExecutionError`` on failure (timeouts are enforced by the runner)."""
        ...


@runtime_checkable
class Evaluator(Protocol):
    """Produces :class:`EvaluationResult` rows for one run. Must explain every score."""

    kind: EvaluatorKind
    key: str

    async def evaluate(self, ctx: EvaluationContext) -> list[EvaluationResult]: ...


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    raw: Any = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None


@runtime_checkable
class LLMClient(Protocol):
    """Chat completion client used by LLM judges and the feedback generator."""

    async def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1500,
        json_schema: dict[str, Any] | None = None,
        timeout_seconds: float = 60.0,
    ) -> LLMResponse: ...
