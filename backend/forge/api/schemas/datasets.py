"""Dataset schemas (``/datasets``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import DatasetKind


class DatasetItemIn(ApiModel):
    """Context item: ``title`` + ``content`` (+ ``source``, ``metadata``).

    Gold item: ``run_id`` (+ ``notes``)."""

    key: str | None = Field(default=None, max_length=200)
    title: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, max_length=200_000)
    source: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None
    run_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)


class DatasetCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    kind: DatasetKind
    slug: str | None = Field(default=None, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    items: list[DatasetItemIn] = Field(default_factory=list, max_length=5000)


class DatasetUpdateIn(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = Field(default=None, max_length=50)


class DatasetItemsIn(ApiModel):
    items: list[DatasetItemIn] = Field(min_length=1, max_length=5000)


class DatasetItemOut(ApiModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    key: str
    content: dict[str, Any]
    run_id: uuid.UUID | None = None
    run: dict[str, Any] | None = Field(default=None, description="Résumé du run (jeux gold)")
    created_at: datetime


class DatasetOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: DatasetKind
    description: str
    version: int
    tags: list[str]
    items_count: int = 0
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class DatasetDetailOut(DatasetOut):
    items: list[DatasetItemOut]
