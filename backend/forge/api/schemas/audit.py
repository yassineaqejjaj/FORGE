"""Audit log schemas (``/audit``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from forge.api.schemas.common import ApiModel
from forge.domain.enums import ActorType


class AuditEventOut(ApiModel):
    id: uuid.UUID
    actor_type: ActorType
    actor_id: uuid.UUID | None = None
    actor_label: str
    action: str
    target_type: str
    target_id: str | None = None
    summary: str
    details: dict[str, Any]
    request_id: str | None = None
    created_at: datetime
