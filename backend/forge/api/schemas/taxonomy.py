"""Criteria catalog and error taxonomy schemas (``/criteria``, ``/error-types``)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import Dimension, ErrorSeverity


class CriterionOut(ApiModel):
    key: str
    dimension: Dimension
    dimension_label: str
    name: str
    question: str
    rubric: str
    scale_min: float
    scale_max: float
    builtin: bool
    judged: bool = Field(description="Noté par les juges / humains (sinon règles ou métriques)")
    created_at: datetime


class CriterionCreateIn(ApiModel):
    key: str = Field(min_length=3, max_length=80, description="« <dimension>.<nom> », ex. quality.tone")
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(default="", max_length=2000)
    rubric: str = Field(default="", max_length=5000)
    scale_min: float = 0.0
    scale_max: float = 5.0


class ErrorTypeOut(ApiModel):
    code: str
    label: str
    description: str
    default_severity: ErrorSeverity
    dimension: Dimension
    builtin: bool
    created_at: datetime


class ErrorTypeCreateIn(ApiModel):
    code: str = Field(min_length=3, max_length=64, description="MAJUSCULES_ET_SOULIGNÉS, ex. WRONG_UNIT")
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    default_severity: ErrorSeverity = ErrorSeverity.medium
    dimension: Dimension = Dimension.quality
