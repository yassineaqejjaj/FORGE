"""Shared API schema building blocks (docs/ARCHITECTURE.md §12)."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 200


class ApiModel(BaseModel):
    """Base for response models built from ORM rows or dataclasses."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[T](ApiModel):
    items: list[T]
    total: int
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class Message(ApiModel):
    detail: str


class IdResponse(ApiModel):
    id: str
