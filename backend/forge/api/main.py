"""FORGE API application: REST ``/api/v1``, OTLP ``/v1/traces``, ``/metrics``, ``/health``, ``/ready``."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from forge.api.errors import install_exception_handlers
from forge.api.routers import API_PREFIX, build_api_router, build_root_router
from forge.config import settings
from forge.infra import cache
from forge.infra.db import dispose_engine, get_engine, get_sessionmaker
from forge.infra.observability.logging_setup import setup_logging
from forge.infra.observability.metrics import metrics_asgi_app
from forge.infra.observability.middleware import RequestContextMiddleware
from forge.infra.observability.tracing import instrument_fastapi, setup_tracing, shutdown_tracing

logger = logging.getLogger("forge.main")

READY_TIMEOUT_SECONDS = 3.0

OPENAPI_TAGS = [
    {"name": "auth", "description": "Connexion, session"},
    {"name": "users", "description": "Utilisateurs et rôles (admin)"},
    {"name": "api-keys", "description": "Clés d'API de service (CI, NOVA, agents)"},
    {"name": "credentials", "description": "Identifiants chiffrés des fournisseurs (admin)"},
    {"name": "meta", "description": "Vocabulaires, énumérations, capacités"},
    {"name": "agents", "description": "Agent Registry : agents, versions, prompts, modèles, outils"},
    {"name": "scenarios", "description": "Scenario Manager : scénarios, versions, variantes"},
    {"name": "datasets", "description": "Jeux de données (contexte, gold)"},
    {"name": "taxonomy", "description": "Critères et taxonomie des erreurs"},
    {"name": "runs", "description": "Evaluation Runs, traces, timeline, manifeste"},
    {"name": "traces", "description": "Ingestion de traces (OTLP/HTTP, événements JSON)"},
    {"name": "evaluations", "description": "Évaluations, scores, erreurs, feedback d'un run"},
    {"name": "reviews", "description": "Évaluation humaine et file de revue"},
    {"name": "judges", "description": "Juges IA"},
    {"name": "evaluation-configs", "description": "Configurations de score (pondérations, garde-fous)"},
    {"name": "benchmarks", "description": "Benchmarks et exécutions"},
    {"name": "experiments", "description": "Expériences baseline / candidate, régressions"},
    {"name": "calibration", "description": "Calibration humaine des juges"},
    {"name": "analytics", "description": "Tableau de bord, explorateur d'erreurs"},
    {"name": "audit", "description": "Journal d'audit"},
    {"name": "system", "description": "Santé et disponibilité"},
]


class Health(BaseModel):
    status: str = "ok"
    version: str = settings.app_version


class DependencyCheck(BaseModel):
    status: str
    latency_ms: float | None = None
    detail: str | None = None
    info: dict[str, Any] | None = None


class Ready(BaseModel):
    status: str
    version: str
    checks: dict[str, DependencyCheck] = Field(default_factory=dict)


async def _bootstrap() -> None:
    from forge.services.bootstrap import ensure_reference_data
    from forge.services.users import ensure_bootstrap_admin

    try:
        async with get_sessionmaker()() as session:
            await ensure_bootstrap_admin(session)
        async with get_sessionmaker()() as session:
            await ensure_reference_data(session)
    except IntegrityError:
        logger.info("Bootstrap data already created by another process")
    except Exception:
        logger.exception("Bootstrap failed (database not ready or not migrated?)")


async def _timed_check(check: Callable[[], Awaitable[dict[str, Any] | None]]) -> DependencyCheck:
    started = time.perf_counter()
    try:
        info = await asyncio.wait_for(check(), timeout=READY_TIMEOUT_SECONDS)
        return DependencyCheck(
            status="ok", latency_ms=round((time.perf_counter() - started) * 1000, 1), info=info
        )
    except TimeoutError:
        return DependencyCheck(status="error", detail="Délai dépassé")
    except Exception as exc:
        return DependencyCheck(status="error", detail=str(exc)[:300] or type(exc).__name__)


async def _check_postgres() -> dict[str, Any]:
    from forge.infra.queue import queue_depth

    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))
        try:
            revision = await conn.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
        except Exception:
            revision = None
    async with get_sessionmaker()() as session:
        depth = await queue_depth(session)
    return {"migration": revision, "queue_depth": depth}


async def _check_valkey() -> dict[str, Any]:
    await cache.ping()
    return {}


async def health() -> Health:
    return Health()


async def ready() -> JSONResponse:
    postgres, valkey = await asyncio.gather(_timed_check(_check_postgres), _timed_check(_check_valkey))
    # Valkey is optional (limits degrade to per-process): only Postgres decides readiness.
    body = Ready(
        status="ok" if postgres.status == "ok" else "degraded",
        version=settings.app_version,
        checks={"postgres": postgres, "valkey": valkey},
    )
    return JSONResponse(
        status_code=200 if postgres.status == "ok" else 503, content=body.model_dump(mode="json")
    )


class _Asgi:
    """Wrap an ASGI callable so that Starlette's ``Route`` treats it as an app."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


def create_app() -> FastAPI:
    setup_logging(settings.log_level)
    setup_tracing(settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("FORGE API %s starting (env=%s)", settings.app_version, settings.env)
        await _bootstrap()
        try:
            yield
        finally:
            logger.info("FORGE API shutting down")
            await cache.close_valkey()
            await dispose_engine()
            shutdown_tracing()

    app = FastAPI(
        title="FORGE API",
        version=settings.app_version,
        description=(
            "Évaluation, benchmark et amélioration continue des agents IA — "
            "aucun score sans explication, tout est versionné et comparable."
        ),
        lifespan=lifespan,
        openapi_tags=OPENAPI_TAGS,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    install_exception_handlers(app)
    app.include_router(build_api_router())
    app.include_router(build_root_router())
    app.add_api_route("/health", health, methods=["GET"], response_model=Health, tags=["system"])
    app.add_api_route(
        "/ready",
        ready,
        methods=["GET"],
        response_model=Ready,
        tags=["system"],
        responses={503: {"model": Ready, "description": "Dépendance indisponible"}},
    )
    app.router.routes.append(Route("/metrics", endpoint=_Asgi(metrics_asgi_app()), include_in_schema=False))
    # CORS is intentionally not enabled: the UI calls the API same-origin through the Next.js proxy.
    app.add_middleware(RequestContextMiddleware)
    instrument_fastapi(app)
    return app


app = create_app()
