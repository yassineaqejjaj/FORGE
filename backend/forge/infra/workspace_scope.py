"""Workspace isolation of the data-access layer (ADR 001 §9, ticket NOV-105, docs/WORKSPACES.md).

One mechanism, applied to every ORM statement of a *bound* session, so that no service can forget it:

* the **workspace of a request** is bound to the database session by the authentication dependency
  (:func:`bind_session`) from the validated identity — the user's membership or the API key's workspace —
  and from nothing else: never a parameter, a header or a body. Workers bind the session to the
  workspace of the job they process. An unbound session (CLI, seed, bootstrap, platform loops) is the
  platform scope and sees everything, exactly as before;
* ``FORGE_WORKSPACE_ENFORCEMENT`` (read on every statement) selects the behaviour:

  - ``off`` (default) — nothing is filtered or counted;
  - ``shadow`` — every row *loaded* outside the bound workspace is logged and counted
    (``forge_workspace_violations_total``); the request is served as before;
  - ``enforce`` — a loader criterion ``workspace_id = <bound workspace>`` is added to every ORM
    SELECT / UPDATE / DELETE on a workspace-scoped table, so a foreign row is *absent*: by-id lookups
    answer 404 exactly like an unknown id, lists and searches never contain it. A row that still
    reaches memory outside the workspace (a filter hole) is counted and refused (:class:`WorkspaceViolation`
    → 404) — defence in depth;

* new rows are stamped with the bound workspace (and the project of a project key) before the flush,
  in every mode; ``workspace_id`` is immutable.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, with_loader_criteria
from sqlalchemy.orm.session import ORMExecuteState

from forge.config import settings
from forge.infra.models.workspace import (
    ORION_DEFAULT_WORKSPACE_ID,
    ProjectScopedMixin,
    WorkspaceScopedMixin,
)
from forge.infra.observability.metrics import record_workspace_violation

logger = logging.getLogger("forge.workspace")

WORKSPACE_KEY = "forge.workspace_id"
PROJECT_KEY = "forge.project_id"


#: Tables **without** a ``workspace_id`` column, each with the reason it is not workspace-scoped. The
#: inventory test (tests/test_workspace_inventory.py) fails when a table is neither scoped nor listed
#: here: a new table must carry the workspace or be reviewed into this list.
EXEMPT_TABLES: dict[str, str] = {
    "workspaces": "the workspace registry itself (a workspace is not a resource of a workspace)",
    "projects": "project registry: owned by a workspace through its own workspace_id, managed by operators",
    "workspace_members": "membership of a user in a workspace; the user's workspace is read from it",
    "project_members": "per-project role of a user, reached through the (workspace-bound) project",
    "external_identities": "OIDC (issuer, sub) -> user link, read before any workspace is known (login); "
    "scoped through its user",
    "users": "identity: scoped through workspace_members (services.users.scope_conditions)",
    "criteria": "global criteria catalog (builtin + custom), shared by every workspace",
    "error_types": "global error taxonomy (builtin + custom codes), shared by every workspace",
    "benchmark_scenarios": "association row, only reached through its (filtered) benchmark",
    "benchmark_agents": "association row, only reached through its (filtered) benchmark",
    "experiment_scenarios": "association row, only reached through its (filtered) experiment",
}


class WorkspaceViolation(Exception):
    """A row outside the caller's workspace reached memory in ``enforce`` mode (a filter hole)."""


def enforcement_mode() -> str:
    return settings.workspace_enforcement


def bind_session(session: Any, workspace_id: uuid.UUID, project_id: uuid.UUID | None = None) -> None:
    """Scope ``session`` (sync or async) to a workspace. Called by authentication and by workers."""
    session.info[WORKSPACE_KEY] = workspace_id
    session.info[PROJECT_KEY] = project_id


def unbind_session(session: Any) -> None:
    session.info.pop(WORKSPACE_KEY, None)
    session.info.pop(PROJECT_KEY, None)


def session_workspace(session: Any) -> uuid.UUID | None:
    value = session.info.get(WORKSPACE_KEY)
    return value if isinstance(value, uuid.UUID) else None


def scope_token(workspace_id: uuid.UUID | None) -> str:
    """What a cache / dedupe key must include to be workspace-specific (``""`` for the default one)."""
    if workspace_id is None or workspace_id == ORION_DEFAULT_WORKSPACE_ID:
        return ""
    return str(workspace_id)


def scoped_key(workspace_id: uuid.UUID | None, key: str) -> str:
    """Prefix a cache / queue / limiter key with the workspace.

    The default workspace keeps the historical key unchanged (existing keys and behaviour are
    preserved); every other workspace gets its own key space.
    """
    token = scope_token(workspace_id)
    return f"ws:{token}:{key}" if token else key


# --- listeners ------------------------------------------------------------------------------------


def _filter_statement(state: ORMExecuteState) -> None:
    if enforcement_mode() != "enforce":
        return
    if state.is_column_load or state.is_relationship_load:
        return
    if not (state.is_select or state.is_update or state.is_delete):
        return
    workspace_id = session_workspace(state.session)
    if workspace_id is None:
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            WorkspaceScopedMixin,
            lambda cls: cls.workspace_id == workspace_id,
            include_aliases=True,
        )
    )


def _check_loaded(session: Session, instance: object) -> None:
    mode = enforcement_mode()
    if mode == "off" or not isinstance(instance, WorkspaceScopedMixin):
        return
    workspace_id = session_workspace(session)
    row_workspace = instance.workspace_id
    if workspace_id is None or row_workspace is None or row_workspace == workspace_id:
        return
    table = type(instance).__tablename__  # type: ignore[attr-defined]
    record_workspace_violation(table, mode)
    logger.warning(
        "workspace violation (%s): %s %s of workspace %s read in workspace %s",
        mode, table, getattr(instance, "id", "?"), row_workspace, workspace_id,
    )  # fmt: skip
    if mode == "enforce":
        raise WorkspaceViolation(table)


def _stamp_and_guard(session: Session, flush_context: object, instances: object) -> None:
    workspace_id = session_workspace(session)
    project_id = session.info.get(PROJECT_KEY)
    mode = enforcement_mode()
    for obj in session.new:
        if not isinstance(obj, WorkspaceScopedMixin):
            continue
        if workspace_id is not None:
            if obj.workspace_id is None:
                obj.workspace_id = workspace_id
            elif obj.workspace_id != workspace_id and mode != "off":
                table = type(obj).__tablename__  # type: ignore[attr-defined]
                record_workspace_violation(table, mode)
                logger.warning("workspace violation (%s): %s created for another workspace", mode, table)
                if mode == "enforce":
                    raise WorkspaceViolation(table)
            if (
                isinstance(obj, ProjectScopedMixin)
                and obj.project_id is None
                and isinstance(project_id, uuid.UUID)
            ):
                obj.project_id = project_id
    for obj in session.dirty:
        if isinstance(obj, WorkspaceScopedMixin):
            state = inspect(obj)
            assert state is not None
            history = state.attrs.workspace_id.history
            if history.has_changes() and history.deleted:
                raise ValueError("workspace_id est immuable")


_installed = False


def install() -> None:
    """Register the listeners once (called when ``forge.infra.models`` is imported)."""
    global _installed
    if _installed:
        return
    _installed = True
    event.listen(Session, "do_orm_execute", _filter_statement)
    event.listen(Session, "loaded_as_persistent", _check_loaded)
    event.listen(Session, "before_flush", _stamp_and_guard)
