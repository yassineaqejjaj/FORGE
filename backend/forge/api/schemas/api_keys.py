"""Service API key schemas (``/api-keys``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import Role


class ApiKeyCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    role: Role = Role.editor
    clearance: int = Field(default=1, ge=0, le=3)
    scopes: list[Literal["traces:write"]] = Field(
        default_factory=list,
        description='Vide = accès complet selon le rôle ; ["traces:write"] = envoi de traces uniquement',
    )
    expires_at: datetime | None = None


class ApiKeyOut(ApiModel):
    id: uuid.UUID
    name: str
    prefix: str
    masked_key: str
    role: Role
    clearance: int
    scopes: list[str]
    created_by: uuid.UUID | None = None
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    active: bool


class ApiKeyCreatedOut(ApiKeyOut):
    key: str = Field(description="Clé complète : affichée une seule fois, conservez-la en lieu sûr")
