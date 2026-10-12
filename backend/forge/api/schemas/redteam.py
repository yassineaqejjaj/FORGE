"""Schemas of the red team router."""

from __future__ import annotations

import uuid

from pydantic import Field

from forge.api.schemas.common import ApiModel


class RedTeamAttackOut(ApiModel):
    key: str
    label: str
    summary: str
    prompt: str
    expected_behavior: str
    scenario_id: uuid.UUID | None = Field(
        default=None, description="null tant que le catalogue n'a pas été installé"
    )


class RedTeamLaunchIn(ApiModel):
    agent_version_id: uuid.UUID
    repetitions: int = Field(default=1, ge=1, le=5)


class RedTeamLaunchOut(ApiModel):
    run_ids: list[uuid.UUID]
    attacks: int


class RedTeamFamilyOut(ApiModel):
    key: str
    label: str
    summary: str
    runs: int
    resisted: int
    resistance: float | None
    status: str = Field(description="solid | fragile | weak | not_run")
    failed_run_ids: list[str]
    error_types: dict[str, int]


class RedTeamReportOut(ApiModel):
    agent_version_id: str
    days: int
    resistance: float | None
    status: str = Field(description="solid | fragile | vulnerable | not_run")
    families: list[RedTeamFamilyOut]
