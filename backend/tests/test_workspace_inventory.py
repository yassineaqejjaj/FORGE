"""Inventory of the workspace filter (ADR 001 §9, ticket NOV-105).

A new table or a new route must either carry the workspace or be reviewed into an explicit exception
list (``forge.infra.workspace_scope.EXEMPT_TABLES``, ``forge.api.deps.UNBOUND_ROUTES``): these tests fail
otherwise, so isolation cannot silently regress when the code grows.
"""

from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import forge.infra.models  # noqa: F401  (registers every table)
from forge.api import deps
from forge.api.routers import API_PREFIX, OPTIONAL_ROUTER_MODULES, ROUTER_MODULES
from forge.infra.db import Base
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID, WorkspaceScopedMixin
from forge.infra.models.workspace import ProjectScopedMixin
from forge.infra.workspace_scope import EXEMPT_TABLES

#: Tables that carry a ``workspace_id`` for their own reasons (not through the scoped-resource mixin).
OWN_WORKSPACE_COLUMN = {"projects", "workspace_members"}


def _scoped_tables() -> dict[str, type]:
    return {
        mapper.local_table.name: mapper.class_
        for mapper in Base.registry.mappers
        if issubclass(mapper.class_, WorkspaceScopedMixin)
    }


def test_every_table_is_workspace_scoped_or_explicitly_exempt() -> None:
    scoped = set(_scoped_tables())
    every = {table.name for table in Base.metadata.sorted_tables}
    undeclared = every - scoped - set(EXEMPT_TABLES)
    assert not undeclared, (
        f"Table(s) without workspace_id and without exemption: {sorted(undeclared)} — add "
        "WorkspaceScopedMixin to the model, or review the table into EXEMPT_TABLES with its reason."
    )
    assert not set(EXEMPT_TABLES) - every, "stale exemption (table no longer exists)"
    assert not set(EXEMPT_TABLES) & scoped, "a scoped table must not be exempt"
    assert all(reason.strip() for reason in EXEMPT_TABLES.values())


def test_scoped_columns_are_mandatory_and_default_to_the_default_workspace() -> None:
    for name, cls in _scoped_tables().items():
        column = Base.metadata.tables[name].c.workspace_id
        assert column.nullable is False, name
        assert column.server_default is not None and str(ORION_DEFAULT_WORKSPACE_ID) in str(
            column.server_default.arg  # type: ignore[union-attr]
        ), name
        (fk,) = column.foreign_keys
        assert fk.column.table.name == "workspaces" and fk.ondelete == "RESTRICT", name
        has_project = "project_id" in Base.metadata.tables[name].c
        assert has_project == issubclass(cls, ProjectScopedMixin), name
        if has_project:
            assert Base.metadata.tables[name].c.project_id.nullable is True, name


async def test_the_migrated_database_matches_the_inventory(db_session: AsyncSession) -> None:
    rows = (
        await db_session.execute(
            text(
                "SELECT table_name, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND column_name = 'workspace_id'"
            )
        )
    ).all()
    in_db = {name: (nullable, default) for name, nullable, default in rows}
    assert set(in_db) == set(_scoped_tables()) | OWN_WORKSPACE_COLUMN
    for name in _scoped_tables():
        nullable, default = in_db[name]
        assert nullable == "NO" and str(ORION_DEFAULT_WORKSPACE_ID) in str(default), name
    not_valid = (
        await db_session.execute(
            text(
                "SELECT conrelid::regclass::text, conname FROM pg_constraint "
                "WHERE contype = 'f' AND NOT convalidated"
            )
        )
    ).all()
    assert not not_valid
    invalid_indexes = (
        await db_session.execute(
            text(
                "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid WHERE NOT i.indisvalid"
            )
        )
    ).all()
    assert not invalid_indexes
    default = (
        await db_session.execute(
            text("SELECT slug FROM workspaces WHERE id = :id"), {"id": ORION_DEFAULT_WORKSPACE_ID}
        )
    ).scalar_one()
    assert default == "default"


def _dependencies(route: APIRoute) -> set[object]:
    found: set[object] = set()

    def walk(dependant: object) -> None:
        for sub in dependant.dependencies:  # type: ignore[attr-defined]
            found.add(sub.call)
            walk(sub)

    walk(route.dependant)
    return found


def _api_routes() -> list[APIRoute]:
    routes: list[APIRoute] = []
    for name in (*ROUTER_MODULES, *OPTIONAL_ROUTER_MODULES):  # optional ones are mounted by a flag
        module = importlib.import_module(f"forge.api.routers.{name}")
        routes += [r for r in module.router.routes if isinstance(r, APIRoute)]
    traces = importlib.import_module("forge.api.routers.traces")
    routes += [r for r in traces.otlp_router.routes if isinstance(r, APIRoute)]
    return routes


BINDING = {deps.get_principal, deps.get_trace_writer, deps.get_current_user}


def test_every_route_binds_the_workspace_or_is_an_explicit_exception() -> None:
    unbound: set[tuple[str, str]] = set()
    for route in _api_routes():
        path = route.path if route.path.startswith("/v1/traces") else f"{API_PREFIX}{route.path}"
        if not _dependencies(route) & BINDING:
            unbound |= {(method, path) for method in route.methods}
    assert unbound == set(deps.UNBOUND_ROUTES), (
        "Routes without a workspace-binding authentication dependency must be listed (with a reason) in "
        f"forge.api.deps.UNBOUND_ROUTES: undeclared={sorted(unbound - set(deps.UNBOUND_ROUTES))} "
        f"stale={sorted(set(deps.UNBOUND_ROUTES) - unbound)}"
    )
    assert all(reason.strip() for reason in deps.UNBOUND_ROUTES.values())


def test_the_inventory_sees_every_mounted_route(app: FastAPI) -> None:
    documented = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    }
    inventoried = {
        (method, route.path if route.path.startswith("/v1/traces") else f"{API_PREFIX}{route.path}")
        for route in _api_routes()
        for method in route.methods
    }
    # /health and /ready are mounted on the application itself (UNBOUND_PLATFORM_PATHS).
    assert documented - inventoried <= {(m, p) for m in ("GET",) for p in deps.UNBOUND_PLATFORM_PATHS}, (
        sorted(documented - inventoried)
    )
