"""Provider credential schemas (``/credentials``). Secrets are write-only."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import ProviderKind


class CredentialCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    kind: ProviderKind
    secret: str | None = Field(default=None, max_length=8000, description="Clé ou jeton (jamais renvoyé)")
    base_url: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] | None = Field(default=None, description="En-têtes supplémentaires (chiffrés)")
    description: str = Field(default="", max_length=2000)


class CredentialUpdateIn(ApiModel):
    name: str | None = Field(
        default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$"
    )
    description: str | None = Field(default=None, max_length=2000)
    secret: str | None = Field(
        default=None, max_length=8000, description='Nouveau secret (rotation) ; "" efface'
    )
    base_url: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] | None = None


class CredentialOut(ApiModel):
    id: uuid.UUID
    name: str
    kind: ProviderKind
    base_url: str | None = None
    secret_hint: str | None = None
    has_secret: bool
    has_headers: bool
    description: str
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    rotated_at: datetime | None = None
    agent_versions_count: int = 0
    judges_count: int = 0
