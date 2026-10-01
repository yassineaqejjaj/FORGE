"""Schemas of ``/judges`` (immutable judge versions, docs §6.1 / §7.3)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import JudgeProvider

_KEY = r"^[a-z0-9][a-z0-9._-]{1,79}$"


class JudgeBehaviourIn(ApiModel):
    provider: JudgeProvider | None = None
    model: str | None = Field(default=None, max_length=200)
    model_version: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=128_000)
    system_prompt: str | None = Field(default=None, max_length=50_000)
    rubric_template: str | None = Field(default=None, max_length=100_000)
    criteria: list[str] | None = Field(default=None, max_length=100)
    weight: float | None = Field(default=None, ge=0)
    base_url: str | None = Field(default=None, max_length=2000)
    credential_id: uuid.UUID | None = None


class JudgeCreateIn(JudgeBehaviourIn):
    key: str = Field(pattern=_KEY, description="Identifiant stable (ex. « claude-judge »)")
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    provider: JudgeProvider
    model: str = Field(min_length=1, max_length=200)
    enabled: bool = True


class JudgeVersionIn(JudgeBehaviourIn):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class JudgeUpdateIn(ApiModel):
    enabled: bool | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)


class JudgeOut(ApiModel):
    id: uuid.UUID
    key: str
    version: int
    name: str
    description: str
    provider: JudgeProvider
    model: str
    model_version: str | None = None
    temperature: float
    max_tokens: int
    system_prompt: str
    rubric_template: str
    criteria: list[str]
    weight: float
    base_url: str | None = None
    credential_id: uuid.UUID | None = None
    enabled: bool
    is_latest: bool
    content_hash: str
    created_by: uuid.UUID | None = None
    created_at: datetime


class JudgeVersionSummary(ApiModel):
    id: uuid.UUID
    version: int
    model: str
    enabled: bool
    is_latest: bool
    content_hash: str
    created_at: datetime


class JudgeDetailOut(JudgeOut):
    versions: list[JudgeVersionSummary] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list, description="Variables disponibles dans la grille")


class JudgeTestIn(ApiModel):
    run_id: uuid.UUID
    criteria: list[str] | None = Field(default=None, description="Critères à évaluer (défaut : ceux du juge)")


class JudgeTestOut(ApiModel):
    judge_id: uuid.UUID
    run_id: uuid.UUID
    status: str
    model: str
    verdicts: list[dict[str, Any]]
    missing: list[str]
    warnings: list[str]
    error: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float | None = None
    latency_ms: float = 0.0
    summary: str | None = None
    prompt: dict[str, Any]
    persisted: bool = False
