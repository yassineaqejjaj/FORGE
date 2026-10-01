"""Trace ingestion (owner: execution) — docs/ARCHITECTURE.md §8.2.

* ``POST /v1/traces`` (root, OTLP/HTTP): protobuf or JSON ``ExportTraceServiceRequest``, gzip
  accepted, body limited to ``FORGE_OTLP_INGEST_MAX_BYTES``; the response follows the OTLP/HTTP
  specification (protobuf ``ExportTraceServiceResponse`` or JSON ``{"partialSuccess": {…}}``).
* ``POST /api/v1/runs/{run_id}/events``: JSON events in the FORGE Agent Protocol format.

Both accept a ``traces:write`` API key or an editor+ principal.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import Response

from forge.api.deps import SessionDep, TraceWriter
from forge.api.errors import ApiError, not_found
from forge.api.schemas.traces import EventsIngestRequest, EventsIngestResponse
from forge.config import settings
from forge.infra.models import EvaluationRun
from forge.services import trace_ingest

router = APIRouter(tags=["traces"])
otlp_router = APIRouter(tags=["traces"])

_CODES = {400: "bad_request", 413: "payload_too_large", 415: "unsupported_media_type"}


async def _read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, f"Traces trop volumineuses (maximum {limit} octets)")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise ApiError(413, f"Traces trop volumineuses (maximum {limit} octets)")
        chunks.append(chunk)
    return b"".join(chunks)


@otlp_router.post(
    "/v1/traces",
    summary="Réception OTLP/HTTP des spans d'un agent",
    response_class=Response,
    responses={
        200: {"description": "ExportTraceServiceResponse (protobuf ou JSON)"},
        413: {"description": "Corps trop volumineux"},
        415: {"description": "Type de contenu non pris en charge"},
    },
)
async def receive_otlp(request: Request, session: SessionDep, principal: TraceWriter) -> Response:
    limit = settings.otlp_ingest_max_bytes
    body = await _read_body(request, limit)
    content_type = request.headers.get("content-type")
    try:
        payload = trace_ingest.decode_otlp(
            body,
            content_type=content_type,
            content_encoding=request.headers.get("content-encoding"),
            max_bytes=limit,
        )
    except trace_ingest.IngestError as exc:
        raise ApiError(exc.status_code, str(exc), code=_CODES.get(exc.status_code)) from exc
    result = await trace_ingest.ingest_otlp(session, payload, clearance=principal.clearance)
    await session.commit()
    content, media_type = trace_ingest.encode_response(
        result, protobuf=trace_ingest.is_protobuf(content_type)
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"X-Forge-Attached-Spans": str(result.attached), "X-Forge-Orphan-Spans": str(result.orphans)},
    )


@router.post(
    "/runs/{run_id}/events",
    response_model=EventsIngestResponse,
    summary="Ajouter des événements (format FORGE Agent Protocol) à la trace d'un run",
)
async def push_run_events(
    run_id: uuid.UUID, body: EventsIngestRequest, session: SessionDep, principal: TraceWriter
) -> EventsIngestResponse:
    run = await session.get(EvaluationRun, run_id)
    if run is None or not trace_ingest.run_visible(run, principal.clearance):
        raise not_found("Run introuvable")
    items = [event.model_dump(mode="json", exclude_none=True) for event in body.events]
    result = await trace_ingest.ingest_events(session, run, items)
    await session.commit()
    return EventsIngestResponse(
        run_id=str(run.id),
        accepted=result.attached,
        duplicates=result.duplicates,
        first_seq=result.first_seq,
        last_seq=result.last_seq,
    )
