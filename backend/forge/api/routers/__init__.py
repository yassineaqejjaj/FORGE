"""API routers. Every module exposes ``router``; :data:`ROUTER_MODULES` fixes the mounting order.

``/api/v1`` routers are listed in :data:`ROUTER_MODULES`; the OTLP receiver (``traces.otlp_router``)
is mounted at the root (``POST /v1/traces``) as the OpenTelemetry specification requires.
"""

from __future__ import annotations

import importlib

from fastapi import APIRouter

API_PREFIX = "/api/v1"

#: (module, owner) — see docs/ARCHITECTURE.md §2.3 for module ownership.
ROUTER_MODULES: tuple[str, ...] = (
    "auth",
    "users",
    "api_keys",
    "credentials",
    "meta",
    "agents",
    "scenarios",
    "datasets",
    "taxonomy",
    "runs",
    "traces",
    "evaluations",
    "reviews",
    "judges",
    "evaluation_configs",
    "benchmarks",
    "experiments",
    "calibration",
    "analytics",
    "redteam",
    "audit",
    "forget",
)


#: Mounted only when the feature is enabled (``FORGE_OIDC_ENABLED``): disabled, the routes do not exist.
OPTIONAL_ROUTER_MODULES: tuple[str, ...] = ("oidc",)


def build_api_router() -> APIRouter:
    from forge.config import settings

    api_router = APIRouter(prefix=API_PREFIX)
    modules = ROUTER_MODULES + (OPTIONAL_ROUTER_MODULES if settings.oidc_enabled else ())
    for name in modules:
        module = importlib.import_module(f"forge.api.routers.{name}")
        api_router.include_router(module.router)
    return api_router


def build_root_router() -> APIRouter:
    """Routes outside ``/api/v1`` (OTLP/HTTP receiver)."""
    module = importlib.import_module("forge.api.routers.traces")
    return module.otlp_router
