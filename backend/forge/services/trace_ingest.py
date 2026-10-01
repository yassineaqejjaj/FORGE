"""Traces pushed by agents (docs/ARCHITECTURE.md §8.2).

* **OTLP/HTTP** (``POST /v1/traces``): protobuf or JSON ``ExportTraceServiceRequest``, optionally
  gzip-compressed. Spans are attached to a run by ``trace_id = run.otel_trace_id``, otherwise by the
  ``forge.run_id`` span/resource attribute; orphans are counted (``forge_otlp_spans_total``) and
  ignored.
* **JSON events** (``POST /api/v1/runs/{id}/events``) in the FORGE Agent Protocol event format.

Events are appended with the next ``seq`` under a row lock on the run (the runner takes the same lock
when it persists the trace, merging and renumbering events pushed during the call). Events arriving
after the run left ``running`` only influence re-evaluations.
"""

from __future__ import annotations

import json
import uuid
import zlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from google.protobuf.json_format import MessageToDict
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTracePartialSuccess,
    ExportTraceServiceRequest,
    ExportTraceServiceResponse,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain.enums import TraceEventSource
from forge.domain.traces.normalize import plan_events
from forge.domain.traces.otlp import count_spans, iter_spans, span_to_event
from forge.domain.traces.protocol import invocation_span_ids, parse_protocol_events
from forge.domain.types import TraceEventData, TraceEventView
from forge.infra.db import utcnow
from forge.infra.models import EvaluationRun, ExecutionTrace, TraceEvent
from forge.infra.observability.metrics import OTLP_SPANS_TOTAL

PROTOBUF_TYPES = frozenset({"application/x-protobuf", "application/protobuf", "application/octet-stream"})
JSON_TYPES = frozenset({"application/json"})


class IngestError(Exception):
    """Invalid trace payload. ``status_code`` follows OTLP/HTTP (400, 413, 415)."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(slots=True)
class IngestResult:
    received: int = 0
    attached: int = 0
    orphans: int = 0
    duplicates: int = 0
    invalid: int = 0
    runs: list[str] = field(default_factory=list)
    first_seq: int | None = None
    last_seq: int | None = None

    @property
    def rejected(self) -> int:
        return self.orphans + self.invalid

    def error_message(self) -> str:
        parts = []
        if self.orphans:
            parts.append(f"{self.orphans} span(s) sans run FORGE correspondant (ignorés)")
        if self.invalid:
            parts.append(f"{self.invalid} span(s) invalides (identifiants ou horodatage manquants)")
        return " ; ".join(parts)


# =====================================================================================================
# OTLP decoding / encoding
# =====================================================================================================


def media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def is_protobuf(content_type: str | None) -> bool:
    return media_type(content_type) in PROTOBUF_TYPES


def decompress(body: bytes, encoding: str | None, *, max_bytes: int) -> bytes:
    """Undo ``Content-Encoding: gzip|deflate`` with a bound on the decompressed size (zip bombs)."""
    value = (encoding or "identity").strip().lower()
    if value in ("", "identity"):
        return body
    if value not in ("gzip", "deflate"):
        raise IngestError(f"Encodage « {encoding} » non pris en charge (gzip attendu)", status_code=415)
    wbits = 16 + zlib.MAX_WBITS if value == "gzip" else zlib.MAX_WBITS
    decoder = zlib.decompressobj(wbits)
    try:
        data = decoder.decompress(body, max_bytes + 1)
    except zlib.error as exc:
        raise IngestError("Corps compressé invalide") from exc
    if len(data) > max_bytes or decoder.unconsumed_tail:
        raise IngestError("Traces trop volumineuses une fois décompressées", status_code=413)
    return data


def decode_otlp(body: bytes, *, content_type: str | None, content_encoding: str | None = None,
                max_bytes: int | None = None) -> dict[str, Any]:  # fmt: skip
    """Raw HTTP body → OTLP/JSON dict (protobuf converted, bytes ids kept base64 and normalised later)."""
    limit = max_bytes or settings.otlp_ingest_max_bytes
    raw = decompress(body, content_encoding, max_bytes=limit)
    kind = media_type(content_type)
    if kind in PROTOBUF_TYPES:
        message = ExportTraceServiceRequest()
        try:
            message.ParseFromString(raw)
        except DecodeError as exc:
            raise IngestError("Message protobuf ExportTraceServiceRequest invalide") from exc
        return MessageToDict(message)
    if kind in JSON_TYPES:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise IngestError("JSON OTLP invalide") from exc
        if not isinstance(data, dict):
            raise IngestError("JSON OTLP invalide : objet ExportTraceServiceRequest attendu")
        return data
    raise IngestError(
        "Type de contenu non pris en charge (application/x-protobuf ou application/json)", status_code=415
    )


def encode_response(result: IngestResult, *, protobuf: bool) -> tuple[bytes, str]:
    """OTLP/HTTP success response: ``partial_success`` set only when spans were rejected."""
    response = ExportTraceServiceResponse()
    if result.rejected:
        response.partial_success.CopyFrom(
            ExportTracePartialSuccess(rejected_spans=result.rejected, error_message=result.error_message())
        )
    if protobuf:
        return response.SerializeToString(), "application/x-protobuf"
    body = MessageToDict(response)
    body.setdefault("partialSuccess", {})
    return json.dumps(body).encode("utf-8"), "application/json"


# =====================================================================================================
# Ingestion
# =====================================================================================================


async def ingest_otlp(
    session: AsyncSession, request: dict[str, Any], *, clearance: int | None = None
) -> IngestResult:
    """Attach the spans of an export request to their runs (flush only; the caller commits).

    Runs whose scenario is above ``clearance`` are treated as unknown (never revealed).
    """
    result = IngestResult(received=count_spans(request))
    spans = list(iter_spans(request))
    result.invalid = max(0, result.received - len(spans))
    by_trace = await _runs_by_trace_id(session, {s.trace_id for s in spans})
    by_id = await _runs_by_id(session, {s.run_id for s in spans if s.run_id and s.trace_id not in by_trace})
    grouped: dict[uuid.UUID, tuple[EvaluationRun, list[TraceEventData]]] = {}
    for span in spans:
        run = by_trace.get(span.trace_id) or (by_id.get(span.run_id) if span.run_id else None)
        if run is None or not run_visible(run, clearance):
            result.orphans += 1
            continue
        event = span_to_event(span, root_span_ids=invocation_span_ids(str(run.id)))
        grouped.setdefault(run.id, (run, []))[1].append(event)
    for run, events in grouped.values():
        added = await append_events(session, run, events)
        result.attached += len(added)
        result.duplicates += len(events) - len(added)
        result.runs.append(str(run.id))
        _track_seq(result, added)
    _count_metrics(result)
    return result


async def ingest_events(
    session: AsyncSession, run: EvaluationRun, items: list[dict[str, Any]]
) -> IngestResult:
    """Append FAP JSON events to a run. Without ``started_at``, ``offset_ms`` is relative to the run start."""
    base = await _origin(session, run)
    events = parse_protocol_events(
        items,
        base_time=base or utcnow(),
        source=TraceEventSource.api,
        key_prefix=f"api:{uuid.uuid4().hex[:8]}:",
    )
    added = await append_events(session, run, events)
    result = IngestResult(received=len(items), attached=len(added), duplicates=len(events) - len(added))
    result.invalid = len(items) - len(events)
    result.runs.append(str(run.id))
    _track_seq(result, added)
    return result


async def append_events(
    session: AsyncSession, run: EvaluationRun, events: list[TraceEventData]
) -> list[TraceEvent]:
    """Append events after the run's last ``seq`` (row lock on the run), skipping known span ids."""
    if not events:
        return []
    await session.execute(select(EvaluationRun.id).where(EvaluationRun.id == run.id).with_for_update())
    existing = {
        span_id: event_id
        for span_id, event_id in await session.execute(
            select(TraceEvent.span_id, TraceEvent.id).where(
                TraceEvent.run_id == run.id, TraceEvent.span_id.is_not(None)
            )
        )
    }
    fresh = [e for e in events if not (e.span_id and e.span_id in existing)]
    if not fresh:
        return []
    last_seq = await session.scalar(select(func.max(TraceEvent.seq)).where(TraceEvent.run_id == run.id)) or 0
    origin = await _origin(session, run) or min(e.started_at for e in fresh)
    planned = plan_events(
        fresh,
        origin=origin,
        max_payload_chars=settings.max_event_payload_chars,
        start_seq=int(last_seq) + 1,
        known_span_ids=frozenset(k for k in existing if k),
    )
    rows = [
        TraceEvent(
            id=uuid.uuid4(),
            run_id=run.id,
            seq=p.seq,
            type=p.type,
            name=p.name,
            source=p.source,
            status=p.status,
            started_at=p.started_at,
            ended_at=p.ended_at,
            offset_ms=p.offset_ms,
            duration_ms=p.duration_ms,
            input=p.input,
            output=p.output,
            attributes=p.attributes,
            span_id=p.span_id,
            parent_span_id=p.parent_span_id,
            parent_id=existing.get(p.external_parent_span_id) if p.external_parent_span_id else None,
        )
        for p in planned
    ]
    session.add_all(rows)
    await session.flush()
    linked = False
    for row, plan in zip(rows, planned, strict=True):
        if plan.parent_index is not None:
            row.parent_id = rows[plan.parent_index].id
            linked = True
    trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run.id))
    if trace is not None:
        trace.event_count = int(last_seq) + len(rows)
    if linked or trace is not None:
        await session.flush()
    return rows


async def load_event_views(session: AsyncSession, run_id: uuid.UUID) -> list[TraceEventView]:
    """Persisted events of a run as :class:`TraceEventView` (ordered by ``seq``)."""
    rows = await session.scalars(
        select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq)
    )
    return [
        TraceEventView(
            id=str(row.id),
            seq=row.seq,
            type=row.type,
            name=row.name,
            offset_ms=row.offset_ms,
            duration_ms=row.duration_ms,
            status=row.status,
            input=row.input,
            output=row.output,
            attributes=dict(row.attributes or {}),
            parent_id=str(row.parent_id) if row.parent_id else None,
        )
        for row in rows
    ]


# --- Helpers ------------------------------------------------------------------------------------------


async def _runs_by_trace_id(session: AsyncSession, trace_ids: set[str]) -> dict[str, EvaluationRun]:
    if not trace_ids:
        return {}
    rows = await session.scalars(select(EvaluationRun).where(EvaluationRun.otel_trace_id.in_(trace_ids)))
    return {run.otel_trace_id: run for run in rows}


async def _runs_by_id(session: AsyncSession, run_ids: set[str | None]) -> dict[str, EvaluationRun]:
    ids: dict[uuid.UUID, str] = {}
    for raw in run_ids:
        try:
            ids[uuid.UUID(str(raw))] = str(raw)
        except ValueError:
            continue
    if not ids:
        return {}
    rows = await session.scalars(select(EvaluationRun).where(EvaluationRun.id.in_(list(ids))))
    return {ids[run.id]: run for run in rows}


def run_visible(run: EvaluationRun, clearance: int | None) -> bool:
    """Whether a caller with ``clearance`` may see (and push events to) the run (docs §3.4)."""
    if clearance is None:
        return True
    level = int(((run.manifest or {}).get("scenario") or {}).get("classification", 1) or 0)
    return level <= int(clearance)


async def _origin(session: AsyncSession, run: EvaluationRun) -> datetime | None:
    started = await session.scalar(select(ExecutionTrace.started_at).where(ExecutionTrace.run_id == run.id))
    return started or run.started_at


def _track_seq(result: IngestResult, rows: list[TraceEvent]) -> None:
    if not rows:
        return
    seqs = [r.seq for r in rows]
    result.first_seq = min(seqs) if result.first_seq is None else min(result.first_seq, *seqs)
    result.last_seq = max(seqs) if result.last_seq is None else max(result.last_seq, *seqs)


def _count_metrics(result: IngestResult) -> None:
    for outcome, value in (
        ("attached", result.attached),
        ("orphan", result.orphans),
        ("duplicate", result.duplicates),
        ("rejected", result.invalid),
    ):
        if value:
            OTLP_SPANS_TOTAL.labels(outcome=outcome).inc(value)
