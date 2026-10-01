"""Schemas of the trace ingestion endpoints (``POST /runs/{id}/events``, ``POST /v1/traces``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import EventStatus

MAX_EVENTS_PER_REQUEST = 1000


class ProtocolEventIn(ApiModel):
    """One event in the FORGE Agent Protocol format (docs/AGENT_PROTOCOL.md §4)."""

    type: str = Field(description="Type d'événement (TraceEventType) ; inconnu → custom")
    name: str | None = None
    id: str | None = Field(default=None, description="Identifiant local (référencé par parent_id)")
    parent_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    offset_ms: float | None = Field(default=None, ge=0, description="Décalage depuis le début du run")
    duration_ms: float | None = Field(default=None, ge=0)
    status: EventStatus = EventStatus.ok
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    span_id: str | None = None
    parent_span_id: str | None = None


class EventsIngestRequest(ApiModel):
    events: list[ProtocolEventIn] = Field(min_length=1, max_length=MAX_EVENTS_PER_REQUEST)


class EventsIngestResponse(ApiModel):
    run_id: str
    accepted: int
    duplicates: int = 0
    first_seq: int | None = None
    last_seq: int | None = None
