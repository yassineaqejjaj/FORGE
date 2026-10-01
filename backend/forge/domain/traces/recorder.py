"""In-memory :class:`~forge.domain.ports.TraceRecorder` used by the Agent Runner (docs §8).

The recorder collects the events of one execution (runner + adapter), accumulates token usage,
model calls, tool calls and cost, and enforces the agent budget: exceeding ``max_tokens`` or
``max_cost`` raises ``AgentExecutionError(error_type="BUDGET_EXCEEDED")`` from :meth:`add_usage`.

Events opened with :meth:`span` become the default parent of events recorded inside the block, so
adapters get a nested timeline for free. The clock is injectable (deterministic tests).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from forge.domain.enums import BuiltinErrorType, EventStatus, TraceEventSource, TraceEventType
from forge.domain.traces.costs import estimate_cost
from forge.domain.types import AgentBudget, AgentExecutionError, ModelSpec, TokenUsage, TraceEventData

Clock = Callable[[], datetime]


def utc_clock() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class _Handle:
    """Mutable handle on an event being recorded (implements ``ports.EventHandle``)."""

    data: TraceEventData

    @property
    def key(self) -> str:
        return self.data.key

    def set_output(self, output: Any) -> None:
        self.data.output = output

    def set_attributes(self, **attributes: Any) -> None:
        self.data.attributes.update(attributes)

    def fail(self, message: str, *, error_type: str | None = None) -> None:
        self.data.status = EventStatus.error
        self.data.attributes["error"] = message
        if error_type:
            self.data.attributes["error_type"] = error_type


class InMemoryTraceRecorder:
    """Collects the trace of one run. Not thread-safe (one recorder per execution)."""

    def __init__(
        self,
        *,
        budget: AgentBudget | None = None,
        model: ModelSpec | None = None,
        clock: Clock = utc_clock,
        source: TraceEventSource = TraceEventSource.adapter,
        key_prefix: str = "e",
    ) -> None:
        self.budget = budget or AgentBudget()
        self.model = model
        self.clock = clock
        self.source = source
        self._key_prefix = key_prefix
        self._counter = itertools.count(1)
        self._events: list[TraceEventData] = []
        self._stack: list[str] = []
        self.usage = TokenUsage()
        self.cost: float | None = None
        self.model_calls = 0
        self.tool_calls = 0

    # --- Port ---------------------------------------------------------------------------------------

    @property
    def events(self) -> Sequence[TraceEventData]:
        return tuple(self._events)

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
        source: TraceEventSource | None = None,
    ) -> str:
        """Record an instantaneous event, or one that just finished after ``duration_ms``."""
        ended = self.clock()
        started = ended - timedelta(milliseconds=max(0.0, duration_ms)) if duration_ms else ended
        data = TraceEventData(
            type=TraceEventType(type),
            name=name,
            started_at=started,
            ended_at=ended,
            key=self._next_key(),
            status=EventStatus(status),
            parent_key=parent if parent is not None else self._current_parent(),
            input=input,
            output=output,
            attributes=dict(attributes or {}),
            source=source or self.source,
        )
        self._events.append(data)
        return data.key

    @contextmanager
    def span(
        self,
        type: TraceEventType,
        name: str,
        *,
        input: Any = None,
        attributes: dict[str, Any] | None = None,
        parent: str | None = None,
        source: TraceEventSource | None = None,
    ) -> Iterator[_Handle]:
        """Time an event. Exceptions (including cancellation) mark it ``error`` and propagate."""
        data = TraceEventData(
            type=TraceEventType(type),
            name=name,
            started_at=self.clock(),
            key=self._next_key(),
            parent_key=parent if parent is not None else self._current_parent(),
            input=input,
            attributes=dict(attributes or {}),
            source=source or self.source,
        )
        self._events.append(data)
        handle = _Handle(data)
        self._stack.append(data.key)
        try:
            yield handle
        except BaseException as exc:
            if data.status != EventStatus.error:
                handle.fail(_describe(exc), error_type=getattr(exc, "error_type", None))
            raise
        finally:
            data.ended_at = self.clock()
            if self._stack and self._stack[-1] == data.key:
                self._stack.pop()
            elif data.key in self._stack:
                self._stack.remove(data.key)

    def add_usage(self, usage: TokenUsage, *, cost: float | None = None, model_call: bool = True) -> None:
        """Accumulate usage (cost estimated from the model pricing when not given) and check the budget."""
        self.usage.add(usage)
        if model_call:
            self.model_calls += 1
        if cost is None:
            cost = estimate_cost(self.model, usage)
        if cost is not None:
            self.cost = (self.cost or 0.0) + max(0.0, float(cost))
        self.check_budget()

    def count_tool_call(self) -> None:
        self.tool_calls += 1

    # --- Extensions (used by adapters through :func:`import_events`) --------------------------------

    def add_event(self, data: TraceEventData) -> str:
        """Append an event built elsewhere (agent-reported, OTLP) keeping its own timestamps."""
        if not data.key:
            data.key = self._next_key()
        if data.parent_key is None and data.parent_span_id is None:
            data.parent_key = self._current_parent()
        self._events.append(data)
        return data.key

    def check_budget(self) -> None:
        """Raise ``BUDGET_EXCEEDED`` when the token or cost budget of the agent is exceeded."""
        max_tokens = self.budget.max_tokens
        if max_tokens is not None and max_tokens > 0 and self.usage.total_tokens > max_tokens:
            raise AgentExecutionError(
                f"Budget de tokens dépassé : {self.usage.total_tokens} tokens consommés "
                f"pour un maximum de {max_tokens}",
                error_type=BuiltinErrorType.BUDGET_EXCEEDED,
            )
        max_cost = self.budget.max_cost
        if max_cost is not None and max_cost > 0 and self.cost is not None and self.cost > max_cost:
            raise AgentExecutionError(
                f"Budget de coût dépassé : {self.cost:.4f} consommé pour un maximum de {max_cost:.4f}",
                error_type=BuiltinErrorType.BUDGET_EXCEEDED,
            )

    def close_open_spans(self, message: str, *, error_type: str | None = None) -> None:
        """Mark every still-open span as failed (the call was interrupted, e.g. by a timeout)."""
        now = self.clock()
        for data in self._events:
            if data.ended_at is None:
                data.ended_at = now
                _Handle(data).fail(message, error_type=error_type)
        self._stack.clear()

    # --- Internals ----------------------------------------------------------------------------------

    def _next_key(self) -> str:
        return f"{self._key_prefix}{next(self._counter)}"

    def _current_parent(self) -> str | None:
        return self._stack[-1] if self._stack else None


def import_events(recorder: Any, events: Iterable[TraceEventData]) -> list[str]:
    """Add externally built events to any recorder (``add_event`` when available, else ``event``)."""
    keys: list[str] = []
    add_event = getattr(recorder, "add_event", None)
    for data in events:
        if callable(add_event):
            keys.append(add_event(data))
            continue
        keys.append(
            recorder.event(
                data.type,
                data.name,
                input=data.input,
                output=data.output,
                attributes=data.attributes,
                status=data.status,
                parent=data.parent_key,
                duration_ms=data.duration_ms,
            )
        )
    return keys


def _describe(exc: BaseException) -> str:
    text = str(exc).strip()
    if text:
        return text
    if isinstance(exc, TimeoutError):
        return "Délai dépassé"
    return type(exc).__name__
