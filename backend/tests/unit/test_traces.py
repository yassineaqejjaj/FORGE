"""Recorder (budget, spans, clock), FAP event parsing, persistence plan and timeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from forge.domain.enums import EventStatus, TraceEventSource, TraceEventType
from forge.domain.traces.costs import estimate_cost, resolve_cost
from forge.domain.traces.normalize import plan_events, truncate_payload
from forge.domain.traces.protocol import invocation_span_id, parse_protocol_events, usage_from_events
from forge.domain.traces.recorder import InMemoryTraceRecorder
from forge.domain.traces.timeline import build_timeline, format_offset
from forge.domain.types import AgentBudget, AgentExecutionError, ModelSpec, TokenUsage, TraceEventView

T0 = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class FakeClock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += timedelta(milliseconds=ms)


def test_recorder_spans_nest_and_time_events() -> None:
    clock = FakeClock()
    recorder = InMemoryTraceRecorder(clock=clock)
    with recorder.span(TraceEventType.llm_call, "Appel") as handle:
        clock.advance(250)
        child = recorder.event(TraceEventType.reasoning, "Pensée", output="ok")
        handle.set_attributes(model="m")
    root, inner = recorder.events
    assert inner.key == child and inner.parent_key == root.key
    assert root.duration_ms == 250 and root.attributes["model"] == "m"
    assert recorder.event(TraceEventType.message, "Après").startswith("e")
    assert recorder.events[-1].parent_key is None


def test_recorder_span_marks_errors_and_propagates() -> None:
    recorder = InMemoryTraceRecorder()
    with pytest.raises(ValueError), recorder.span(TraceEventType.tool_call, "outil"):
        raise ValueError("boum")
    event = recorder.events[0]
    assert event.status == EventStatus.error and event.attributes["error"] == "boum"
    assert event.ended_at is not None


def test_recorder_enforces_token_and_cost_budget() -> None:
    recorder = InMemoryTraceRecorder(budget=AgentBudget(max_tokens=100))
    recorder.add_usage(TokenUsage(40, 40))
    with pytest.raises(AgentExecutionError) as exc:
        recorder.add_usage(TokenUsage(10, 20))
    assert exc.value.error_type == "BUDGET_EXCEEDED" and not exc.value.retryable
    priced = ModelSpec(provider="openai", model="m", input_cost_per_mtok=1000.0, output_cost_per_mtok=0.0)
    recorder = InMemoryTraceRecorder(budget=AgentBudget(max_cost=0.5), model=priced)
    recorder.add_usage(TokenUsage(400, 0))  # cost 0.4 estimated from pricing
    assert recorder.cost == pytest.approx(0.4) and recorder.model_calls == 1
    with pytest.raises(AgentExecutionError, match="Budget de coût"):
        recorder.add_usage(TokenUsage(200, 0))


def test_close_open_spans_after_interruption() -> None:
    recorder = InMemoryTraceRecorder()
    context = recorder.span(TraceEventType.llm_call, "long")
    context.__enter__()
    recorder.close_open_spans("Délai dépassé", error_type="TIMEOUT")
    assert recorder.events[0].status == EventStatus.error
    assert recorder.events[0].attributes["error_type"] == "TIMEOUT"


def test_costs_prefer_pricing_then_agent_report() -> None:
    model = ModelSpec(provider="x", model="m", input_cost_per_mtok=2.0, output_cost_per_mtok=8.0)
    assert estimate_cost(model, TokenUsage(1_000_000, 500_000)) == pytest.approx(6.0)
    assert estimate_cost(ModelSpec(provider="x", model="m"), TokenUsage(10, 10)) is None
    assert resolve_cost(model, TokenUsage(1000, 0), 9.0) == (pytest.approx(0.002), "pricing")
    assert resolve_cost(None, TokenUsage(1000, 0), 0.03) == (0.03, "agent")
    assert resolve_cost(None, TokenUsage(), None) == (None, None)


def test_protocol_events_parse_timing_parents_and_unknown_types() -> None:
    events = parse_protocol_events(
        [
            {"id": "a", "type": "llm_call", "name": "Génération", "offset_ms": 100, "duration_ms": 400,
             "model": "m", "input_tokens": 10, "output_tokens": 5, "cost": 0.01},
            {"id": "b", "parent_id": "a", "type": "thought", "output": "je réfléchis"},
            {"type": "weird", "name": "Étape"},
            "ignored",
        ],
        base_time=T0,
    )  # fmt: skip
    first, second, third = events
    assert first.started_at == T0 + timedelta(milliseconds=100) and first.duration_ms == 400
    assert first.attributes["model"] == "m"
    assert second.type == TraceEventType.reasoning and second.parent_key == first.key
    assert second.started_at == first.ended_at  # cursor: previous event's end
    assert third.type == TraceEventType.custom and third.attributes["original_type"] == "weird"
    usage, calls, cost = usage_from_events(events)
    assert (usage.input_tokens, usage.output_tokens, calls, cost) == (10, 5, 1, 0.01)


def test_plan_orders_numbers_truncates_and_resolves_parents() -> None:
    events = parse_protocol_events(
        [
            {"id": "child", "parent_id": "root", "type": "tool_call", "name": "jira.search", "offset_ms": 50,
             "input": {"query": "x" * 50}},
            {"id": "root", "type": "custom", "name": "Agent", "offset_ms": 10, "duration_ms": 500},
            {"id": "loop", "parent_id": "loop", "type": "message", "offset_ms": 60},
        ],
        base_time=T0,
    )  # fmt: skip
    planned = plan_events(events, origin=T0, max_payload_chars=20)
    assert [p.seq for p in planned] == [1, 2, 3]
    assert [p.name for p in planned] == ["Agent", "jira.search", "message"]
    assert planned[1].parent_index == 0 and planned[2].parent_index is None
    assert planned[0].offset_ms == 10
    assert planned[1].input["_truncated"] is True  # structure larger than the limit → preview
    assert plan_events(events, origin=T0, max_payload_chars=1000)[1].input == {"query": "x" * 50}


def test_truncate_payload_structures() -> None:
    assert truncate_payload("abc", 10) == "abc"
    big = truncate_payload([{"k": "v" * 5} for _ in range(50)], 100)
    assert big["_truncated"] is True and len(big["preview"]) == 100


def test_invocation_span_id_is_deterministic() -> None:
    assert invocation_span_id("run", 1) == invocation_span_id("run", 1)
    assert invocation_span_id("run", 1) != invocation_span_id("run", 2)
    assert len(invocation_span_id("run", 1)) == 16


def _view(seq: int, type: TraceEventType, offset: float, duration: float | None, **kw) -> TraceEventView:
    return TraceEventView(id=f"id{seq}", seq=seq, type=type, name=kw.pop("name", type.value), offset_ms=offset,
                          duration_ms=duration, status=kw.pop("status", EventStatus.ok), **kw)  # fmt: skip


def test_timeline_items_labels_depth_and_stats() -> None:
    events = [
        _view(1, TraceEventType.run_started, 0, 0),
        _view(2, TraceEventType.llm_call, 100, 1200, attributes={"model": "gpt", "input_tokens": 900,
              "output_tokens": 100, "cost": 0.002}),
        _view(3, TraceEventType.tool_call, 1300, 300, name="jira.search", parent_id="id2",
              attributes={"tool": "jira.search", "arguments": {"query": "export"}}),
        _view(4, TraceEventType.tool_result, 1600, 0, parent_id="id3", output="3 tickets",
              attributes={"tool": "jira.search"}),
        _view(5, TraceEventType.error, 1700, None, status=EventStatus.error, attributes={"error": "panne"}),
        _view(6, TraceEventType.final_answer, 1800, 0, output="Voici le PRD"),
    ]  # fmt: skip
    timeline = build_timeline(list(reversed(events)))
    items = {i.seq: i for i in timeline.items}
    assert [i.seq for i in timeline.items] == [1, 2, 3, 4, 5, 6]
    assert items[2].label == "Appel au modèle" and items[2].offset_label == "00:00.1"
    assert items[2].summary == "gpt · 900 → 100 tokens · coût 0.0020" and items[2].tokens == 1000
    assert items[3].depth == 1 and items[4].depth == 2
    assert items[3].summary == "jira.search(query=« export »)"
    assert items[5].summary == "Échec : panne"
    assert items[6].summary == "Voici le PRD"
    assert timeline.llm_calls == 1 and timeline.tool_calls == 1 and timeline.errors == 1
    assert timeline.total_duration_ms == 1800
    assert timeline.by_type[0].type == TraceEventType.llm_call and timeline.by_type[0].share == pytest.approx(
        0.6667
    )
    assert timeline.slowest_steps[0].seq == 2


def test_format_offset() -> None:
    assert format_offset(1234) == "00:01.2"
    assert format_offset(61_000) == "01:01.0"
    assert format_offset(3_725_400) == "1:02:05.4"
    assert format_offset(None) == "00:00.0"


def test_recorder_add_event_keeps_timestamps() -> None:
    recorder = InMemoryTraceRecorder(source=TraceEventSource.adapter)
    (event,) = parse_protocol_events(
        [{"type": "message", "started_at": "2026-03-01T09:00:05Z"}], base_time=T0
    )
    recorder.add_event(event)
    assert recorder.events[0].started_at == T0 + timedelta(seconds=5)
