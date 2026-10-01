"""Timeline of a run built from its persisted events (``GET /runs/{id}/timeline``).

:func:`build_timeline` turns :class:`TraceEventView` rows into display items (French labels,
``00:01.2`` offsets, nesting depth, one-line summaries) plus duration statistics per event type and
the slowest steps. Works on redacted events too (summaries then only use safe attributes).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from forge.domain.enums import EventStatus, TraceEventType
from forge.domain.types import TraceEventView

EVENT_TYPE_LABELS: dict[TraceEventType, str] = {
    TraceEventType.run_started: "Démarrage du run",
    TraceEventType.context_prepared: "Contexte préparé",
    TraceEventType.reasoning: "Raisonnement",
    TraceEventType.message: "Message",
    TraceEventType.llm_call: "Appel au modèle",
    TraceEventType.tool_call: "Appel d'outil",
    TraceEventType.tool_result: "Résultat d'outil",
    TraceEventType.retrieval: "Recherche documentaire",
    TraceEventType.memory: "Mémoire",
    TraceEventType.agent_handoff: "Délégation à un agent",
    TraceEventType.decision: "Décision",
    TraceEventType.error: "Erreur",
    TraceEventType.final_answer: "Réponse finale",
    TraceEventType.run_completed: "Fin du run",
    TraceEventType.custom: "Étape",
}

SUMMARY_MAX_CHARS = 160
SLOWEST_STEPS = 5


@dataclass(slots=True)
class TimelineItem:
    seq: int
    id: str
    parent_id: str | None
    offset_ms: float
    offset_label: str
    type: TraceEventType
    label: str
    name: str
    summary: str
    duration_ms: float | None
    status: EventStatus
    depth: int
    model: str | None = None
    tool: str | None = None
    agent: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    tokens: int | None = None
    cost: float | None = None


@dataclass(slots=True)
class TypeStats:
    type: TraceEventType
    label: str
    count: int
    total_duration_ms: float
    mean_duration_ms: float | None
    max_duration_ms: float | None
    share: float  # summed duration / timeline duration, capped at 1 (nested events overlap)


@dataclass(slots=True)
class StepStats:
    seq: int
    label: str
    type: TraceEventType
    duration_ms: float
    share: float


@dataclass(slots=True)
class Timeline:
    items: list[TimelineItem]
    total_duration_ms: float
    by_type: list[TypeStats] = field(default_factory=list)
    slowest_steps: list[StepStats] = field(default_factory=list)
    llm_calls: int = 0
    tool_calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None


def format_offset(ms: float | None) -> str:
    """``00:01.2`` (minutes:seconds.tenths), ``1:02:03.4`` beyond one hour."""
    tenths = max(0, round((ms or 0.0) / 100))
    seconds, tenth = divmod(tenths, 10)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minute:02d}:{sec:02d}.{tenth}"
    return f"{minutes:02d}:{sec:02d}.{tenth}"


def format_duration(ms: float | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.1f} s".replace(".", ",")


def build_timeline(events: list[TraceEventView]) -> Timeline:
    ordered = sorted(events, key=lambda e: e.seq)
    depths = _depths(ordered)
    items = [_item(event, depths.get(event.id, 0)) for event in ordered]
    total = _total_duration(ordered)
    timeline = Timeline(items=items, total_duration_ms=total)
    timeline.by_type = _type_stats(ordered, total)
    timeline.slowest_steps = _slowest(items, total)
    _totals(timeline, items)
    return timeline


# --- Items ------------------------------------------------------------------------------------------


def _item(event: TraceEventView, depth: int) -> TimelineItem:
    attrs = event.attributes or {}
    input_tokens = _int(attrs.get("input_tokens"))
    output_tokens = _int(attrs.get("output_tokens"))
    tokens = None
    if input_tokens is not None or output_tokens is not None:
        tokens = (input_tokens or 0) + (output_tokens or 0)
    is_tool = event.type in (TraceEventType.tool_call, TraceEventType.tool_result)
    return TimelineItem(
        seq=event.seq,
        id=event.id,
        parent_id=event.parent_id,
        offset_ms=event.offset_ms,
        offset_label=format_offset(event.offset_ms),
        type=event.type,
        label=EVENT_TYPE_LABELS.get(event.type, "Étape"),
        name=event.name,
        summary=summarize(event),
        duration_ms=event.duration_ms,
        status=event.status,
        depth=depth,
        model=_str(attrs.get("model")),
        tool=_str(attrs.get("tool")) if is_tool else None,
        agent=_str(attrs.get("agent")),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tokens=tokens,
        cost=_float(attrs.get("cost")),
    )


def summarize(event: TraceEventView) -> str:
    """One-line French summary of an event (bounded length)."""
    attrs = event.attributes or {}
    if event.status == EventStatus.error:
        message = attrs.get("error") or _preview(event.output) or "échec"
        return _clip(f"Échec : {message}")
    builder = _SUMMARIES.get(event.type)
    text = builder(event, attrs) if builder else ""
    return _clip(text or _preview(event.output) or _preview(event.input) or event.name)


def _llm_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    parts = [str(attrs["model"])] if attrs.get("model") else []
    if attrs.get("input_tokens") is not None or attrs.get("output_tokens") is not None:
        tokens_in = _int(attrs.get("input_tokens")) or 0
        tokens_out = _int(attrs.get("output_tokens")) or 0
        parts.append(f"{tokens_in} → {tokens_out} tokens")
    cost = _float(attrs.get("cost"))
    if cost:
        parts.append(f"coût {cost:.4f}")
    return " · ".join(parts)


def _tool_call_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    tool = attrs.get("tool") or event.name
    arguments = attrs.get("arguments", event.input)
    return f"{tool}({_compact(arguments)})" if arguments not in (None, {}, "") else f"{tool}()"


def _tool_result_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    tool = attrs.get("tool") or event.name
    preview = _preview(event.output)
    return f"{tool} → {preview}" if preview else str(tool)


def _retrieval_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    documents = attrs.get("documents")
    count = _int(attrs.get("documents_count"))
    if isinstance(documents, list):
        count = count if count is not None else len(documents)
        listed = ", ".join(str(d) for d in documents[:5])
        more = "…" if len(documents) > 5 else ""
        return f"{count} document(s) : {listed}{more}" if documents else f"{count} document(s)"
    return f"{count} document(s)" if count is not None else ""


def _context_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    parts = []
    if attrs.get("context_source"):
        parts.append(f"source : {attrs['context_source']}")
    if attrs.get("documents_count") is not None:
        parts.append(f"{attrs['documents_count']} document(s)")
    if attrs.get("snapshot_version"):
        parts.append(f"snapshot v{attrs['snapshot_version']}")
    if attrs.get("orbit_request_id"):
        parts.append(f"requête ORBIT {attrs['orbit_request_id']}")
    return " · ".join(parts)


def _handoff_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    target = attrs.get("agent") or attrs.get("to")
    source = attrs.get("from")
    if source and target:
        return f"{source} → {target}"
    return f"→ {target}" if target else ""


def _run_completed_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    parts = []
    if attrs.get("total_tokens") is not None:
        parts.append(f"{attrs['total_tokens']} tokens")
    if attrs.get("cost") is not None:
        parts.append(f"coût {float(attrs['cost']):.4f}")
    if attrs.get("latency_ms") is not None:
        parts.append(f"latence {format_duration(float(attrs['latency_ms']))}")
    return " · ".join(parts)


def _text_summary(event: TraceEventView, attrs: dict[str, Any]) -> str:
    return _preview(event.output) or _preview(event.input)


_SUMMARIES = {
    TraceEventType.llm_call: _llm_summary,
    TraceEventType.tool_call: _tool_call_summary,
    TraceEventType.tool_result: _tool_result_summary,
    TraceEventType.retrieval: _retrieval_summary,
    TraceEventType.context_prepared: _context_summary,
    TraceEventType.agent_handoff: _handoff_summary,
    TraceEventType.run_completed: _run_completed_summary,
    TraceEventType.reasoning: _text_summary,
    TraceEventType.message: _text_summary,
    TraceEventType.decision: _text_summary,
    TraceEventType.final_answer: _text_summary,
}


# --- Statistics -------------------------------------------------------------------------------------


def _depths(events: list[TraceEventView]) -> dict[str, int]:
    parents = {e.id: e.parent_id for e in events}
    depths: dict[str, int] = {}
    for event in events:
        depth, current, seen = 0, event.parent_id, {event.id}
        while current is not None and current in parents and current not in seen:
            seen.add(current)
            depth += 1
            current = parents[current]
        depths[event.id] = depth
    return depths


def _total_duration(events: list[TraceEventView]) -> float:
    if not events:
        return 0.0
    end = max(e.offset_ms + (e.duration_ms or 0.0) for e in events)
    start = min(e.offset_ms for e in events)
    return round(max(0.0, end - start), 3)


def _type_stats(events: list[TraceEventView], total: float) -> list[TypeStats]:
    grouped: dict[TraceEventType, list[TraceEventView]] = {}
    for event in events:
        grouped.setdefault(event.type, []).append(event)
    stats: list[TypeStats] = []
    for event_type, group in grouped.items():
        durations = [e.duration_ms for e in group if e.duration_ms is not None]
        summed = round(sum(durations), 3)
        stats.append(
            TypeStats(
                type=event_type,
                label=EVENT_TYPE_LABELS.get(event_type, "Étape"),
                count=len(group),
                total_duration_ms=summed,
                mean_duration_ms=round(summed / len(durations), 3) if durations else None,
                max_duration_ms=max(durations) if durations else None,
                share=round(min(1.0, summed / total), 4) if total > 0 else 0.0,
            )
        )
    stats.sort(key=lambda s: s.total_duration_ms, reverse=True)
    return stats


def _slowest(items: list[TimelineItem], total: float) -> list[StepStats]:
    timed = [
        i for i in items
        if i.duration_ms and i.type not in (TraceEventType.run_started, TraceEventType.run_completed)
    ]  # fmt: skip
    timed.sort(key=lambda i: i.duration_ms or 0.0, reverse=True)
    return [
        StepStats(
            seq=i.seq,
            label=f"{i.label} — {i.name}" if i.name and i.name != i.label else i.label,
            type=i.type,
            duration_ms=float(i.duration_ms or 0.0),
            share=round(min(1.0, (i.duration_ms or 0.0) / total), 4) if total > 0 else 0.0,
        )
        for i in timed[:SLOWEST_STEPS]
    ]


def _totals(timeline: Timeline, items: list[TimelineItem]) -> None:
    for item in items:
        if item.type == TraceEventType.llm_call:
            timeline.llm_calls += 1
            timeline.input_tokens += item.input_tokens or 0
            timeline.output_tokens += item.output_tokens or 0
            if item.cost is not None:
                timeline.cost = (timeline.cost or 0.0) + item.cost
        elif item.type == TraceEventType.tool_call:
            timeline.tool_calls += 1
        if item.status == EventStatus.error:
            timeline.errors += 1
    if timeline.cost is not None:
        timeline.cost = round(timeline.cost, 8)


# --- Formatting helpers -----------------------------------------------------------------------------


def _clip(text: str, limit: int = SUMMARY_MAX_CHARS) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _compact(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k}={_compact_scalar(v)}" for k, v in list(value.items())[:4])
    return _compact_scalar(value)


def _compact_scalar(value: Any) -> str:
    if isinstance(value, str):
        return f"« {_clip(value, 40)} »"
    try:
        return _clip(json.dumps(value, ensure_ascii=False, default=str), 40)
    except (TypeError, ValueError):
        return _clip(str(value), 40)


def _preview(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        return _clip(value)
    if isinstance(value, dict):
        for key in ("text", "content", "message", "summary", "answer"):
            if isinstance(value.get(key), str) and value[key]:
                return _clip(value[key])
    if isinstance(value, list) and value and isinstance(value[-1], dict):
        content = value[-1].get("content")
        if isinstance(content, str) and content:
            return _clip(content)
    try:
        return _clip(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return _clip(str(value))


def _str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
