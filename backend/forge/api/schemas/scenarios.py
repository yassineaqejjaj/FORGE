"""Scenario Manager schemas (``/scenarios``, ``/scenario-versions``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import Difficulty, ScenarioVisibility


class ScenarioContentIn(ApiModel):
    """Content of a scenario version (hashed). Validated by ``forge.domain.scenarios.validation``."""

    description: str | None = Field(default=None, max_length=20_000)
    difficulty: Difficulty | None = None
    input: dict[str, Any] | None = Field(default=None, description='{"prompt": …} ou {"messages": […]}')
    context: dict[str, Any] | None = Field(
        default=None, description='{"documents": [{id, title, content, source}]}'
    )
    constraints: list[str] | None = None
    expected_output: Any = None
    expected_behavior: str | None = Field(default=None, max_length=20_000)
    criteria: list[dict[str, Any] | str] | None = Field(
        default=None, description="[{key, weight?, question?, rubric?}]"
    )
    rules: list[dict[str, Any]] | None = Field(default=None, description="RuleSpec : {id?, type, params, …}")
    tool_mocks: list[dict[str, Any]] | None = None
    dataset_id: uuid.UUID | None = None


class ScenarioCreateIn(ApiModel):
    slug: str | None = Field(
        default=None, max_length=120, description="Ex. scenario_prd_001 (généré si absent)"
    )
    name: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=100, description="Texte libre (liste suggérée dans /meta)")
    visibility: ScenarioVisibility = ScenarioVisibility.public
    classification: int = Field(default=1, ge=0, le=3)
    tags: list[str] = Field(default_factory=list, max_length=50)
    fresh_until: datetime | None = Field(default=None, description="Scénarios fresh : défaut +30 jours")
    changelog: str = Field(default="", max_length=10_000)
    content: ScenarioContentIn


class ScenarioUpdateIn(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=50)
    visibility: ScenarioVisibility | None = None
    classification: int | None = Field(default=None, ge=0, le=3)
    archived: bool | None = None
    fresh_until: datetime | None = None


class ScenarioVersionCreateIn(ApiModel):
    """Fields given replace those of the latest version; the others are kept."""

    content: ScenarioContentIn
    changelog: str = Field(default="", max_length=10_000)


class VariantCreateIn(ApiModel):
    label: str = Field(min_length=1, max_length=60, description="Ex. short_context")
    name: str | None = Field(default=None, max_length=300)
    overrides: ScenarioContentIn = Field(default_factory=ScenarioContentIn)
    tags: list[str] | None = None
    visibility: ScenarioVisibility | None = None
    changelog: str = Field(default="", max_length=10_000)


class ScenarioVersionOut(ApiModel):
    id: uuid.UUID
    scenario_id: uuid.UUID
    version: int
    changelog: str
    content_hash: str
    created_at: datetime
    created_by: uuid.UUID | None = None
    redacted: bool
    description: str | None = None
    difficulty: Difficulty
    input: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    constraints: list[str] | None = None
    expected_output: Any = None
    expected_behavior: str | None = None
    criteria: list[dict[str, Any]]
    rules: list[dict[str, Any]]
    tool_mocks: list[dict[str, Any]] | None = None
    dataset_id: str | None = None
    canary: str | None = Field(default=None, description="Visible des mainteneurs uniquement")


class ScenarioVersionSummary(ApiModel):
    id: uuid.UUID
    version: int
    difficulty: Difficulty
    changelog: str
    content_hash: str
    created_at: datetime
    created_by: uuid.UUID | None = None


class ScenarioOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    category: str
    category_label: str
    visibility: ScenarioVisibility
    classification: int
    classification_warning: str | None = None
    tags: list[str]
    family_id: uuid.UUID
    parent_scenario_id: uuid.UUID | None = None
    variant_label: str | None = None
    latest_version: int
    latest_version_id: uuid.UUID | None = None
    difficulty: Difficulty | None = None
    archived: bool
    fresh_until: datetime | None = None
    is_fresh: bool
    owner_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class FamilyMember(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    variant_label: str | None = None
    parent_scenario_id: uuid.UUID | None = None
    visibility: ScenarioVisibility


class ScenarioDetailOut(ScenarioOut):
    latest: ScenarioVersionOut | None = None
    versions: list[ScenarioVersionSummary]
    family: list[FamilyMember]


class ImportIn(ApiModel):
    bundle: dict[str, Any] | None = Field(default=None, description="Bundle forge.scenarios/v1 (objet)")
    content: str | None = Field(default=None, description="Bundle sous forme de texte YAML ou JSON")
    dry_run: bool = False


class ImportItem(ApiModel):
    slug: str | None = None
    scenario_id: str | None = None
    versions: list[int] = Field(default_factory=list)
    reason: str | None = None


class ImportErrorItem(ApiModel):
    index: int | None = None
    slug: str | None = None
    message: str
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ImportReportOut(ApiModel):
    dry_run: bool
    created: list[ImportItem]
    updated: list[ImportItem]
    skipped: list[ImportItem]
    errors: list[ImportErrorItem]
