"""Access helpers shared by services and routers (classification & private scenarios, docs §3).

Services never import ``forge.api``: they receive any object implementing :class:`Viewer`
(``forge.api.deps.Principal`` does).
"""

from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import ColumnElement

from forge.domain.enums import ScenarioVisibility
from forge.infra.models import Scenario


class Viewer(Protocol):
    @property
    def clearance(self) -> int: ...

    @property
    def can_see_private(self) -> bool: ...


def classification_condition(viewer: Viewer) -> ColumnElement[bool]:
    """SQL condition restricting scenarios (and, by join, runs) to the viewer's clearance.

    Scenarios above the clearance are **not revealed** (404 on detail, absent from lists).
    """
    return Scenario.classification <= int(viewer.clearance)


def can_view_scenario(viewer: Viewer, scenario: Scenario) -> bool:
    return int(scenario.classification) <= int(viewer.clearance)


def must_redact(viewer: Viewer, visibility: ScenarioVisibility | str | None) -> bool:
    """True when private content must be masked for this viewer."""
    return (
        ScenarioVisibility(visibility or "public") == ScenarioVisibility.private
        and not viewer.can_see_private
    )


def manifest_visibility(manifest: dict[str, Any]) -> str:
    return str((manifest.get("scenario") or {}).get("visibility") or "public")
