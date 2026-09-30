"""Test fixtures.

Unit tests (``tests/unit``) need nothing. Integration tests run against the docker compose
infrastructure (``make infra``):

* Postgres on ``localhost:5434`` — a dedicated database (default ``forge_test``, override with
  ``FORGE_TEST_DATABASE`` to run several suites in parallel) is (re)created and migrated once per
  session;
* Valkey on ``localhost:6381`` database 15.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
PG_SERVER_URL = os.environ.get("FORGE_TEST_PG_URL", "postgresql://forge:forge@localhost:5434")
TEST_DATABASE = os.environ.get("FORGE_TEST_DATABASE", "forge_test")
ADMIN_EMAIL = "admin@forge.local"
ADMIN_PASSWORD = "forge-admin"
DEFAULT_PASSWORD = "Mot-de-passe-123"

# Must be set before any ``forge`` import (settings are read at import time).
os.environ.update(
    {
        "FORGE_ENV": "test",
        "FORGE_DATABASE_URL": f"{PG_SERVER_URL.replace('postgresql://', 'postgresql+asyncpg://', 1)}/{TEST_DATABASE}",
        "FORGE_VALKEY_URL": os.environ.get("FORGE_TEST_VALKEY_URL", "redis://localhost:6381/15"),
        "FORGE_JWT_SECRET": "forge-test-secret-0123456789abcdef0123456789",
        "FORGE_SECRETS_KEY": "forge-test-secrets-key-0123456789abcdef0123",
        "FORGE_OTLP_ENDPOINT": "",
        "FORGE_OPENAI_API_KEY": "",
        "FORGE_ANTHROPIC_API_KEY": "",
        "FORGE_FEEDBACK_LLM_BASE_URL": "",
        "FORGE_FEEDBACK_LLM_MODEL": "",
        "FORGE_BOOTSTRAP_ADMIN_EMAIL": ADMIN_EMAIL,
        "FORGE_BOOTSTRAP_ADMIN_PASSWORD": ADMIN_PASSWORD,
        "FORGE_WORKER_METRICS_PORT": "0",
        "FORGE_TRACE_GRACE_SECONDS": "0",
        "FORGE_LOG_LEVEL": "WARNING",
        "FORGE_DEMO_AGENTS_URL": "http://demo-agents.invalid",
    }
)

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from forge.domain.enums import Role  # noqa: E402


async def _recreate_database() -> None:
    try:
        conn = await asyncpg.connect(f"{PG_SERVER_URL}/postgres", timeout=10)
    except (OSError, asyncpg.PostgresError) as exc:
        raise RuntimeError(
            f"Postgres de test injoignable ({PG_SERVER_URL}). Lancez `make infra` (docker compose) : {exc}"
        ) from exc
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DATABASE}" WITH (FORCE)')
        await conn.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    finally:
        await conn.close()


@pytest.fixture(scope="session")
def database() -> str:
    """Create and migrate the test database (once per session)."""
    asyncio.run(_recreate_database())
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
    )
    return os.environ["FORGE_DATABASE_URL"]


@pytest_asyncio.fixture(scope="session")
async def app(database: str) -> AsyncIterator[FastAPI]:
    from forge.api.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def _client(app: FastAPI, **kwargs: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, **kwargs)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(app) as c:
        yield c


@pytest_asyncio.fixture
async def lenient_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client that turns unhandled server errors into 500 responses instead of raising."""
    async with _client(app, raise_app_exceptions=False) as c:
        yield c


async def login(client: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response


@pytest_asyncio.fixture
async def admin_client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Client authenticated as the bootstrap admin (session JWT sent as a Bearer token)."""
    async with _client(app) as c:
        c.headers["Authorization"] = f"Bearer {await token_for(ADMIN_EMAIL)}"
        yield c


@pytest_asyncio.fixture
async def db_session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    from forge.infra.db import get_sessionmaker

    async with get_sessionmaker()() as session:
        yield session


async def token_for(email: str) -> str:
    """Session JWT for an existing user (bypasses the login endpoint)."""
    from forge.infra.db import get_sessionmaker
    from forge.infra.security import create_access_token
    from forge.services.users import get_by_email

    async with get_sessionmaker()() as session:
        user = await get_by_email(session, email)
        assert user is not None, email
        return create_access_token(user.id, password_hash=user.password_hash)


@dataclass
class UserInfo:
    id: object
    email: str
    password: str
    role: Role


@pytest_asyncio.fixture
async def make_user(app: FastAPI) -> Callable[..., Awaitable[UserInfo]]:
    import uuid

    from forge.infra.db import get_sessionmaker
    from forge.services.users import create_user

    async def _make(role: Role = Role.viewer, *, clearance: int = 1) -> UserInfo:
        email = f"user-{uuid.uuid4().hex[:8]}@example.com"
        async with get_sessionmaker()() as session:
            user = await create_user(
                session, email=email, full_name=f"Utilisateur {role.value}", password=DEFAULT_PASSWORD,
                role=role, clearance=clearance,
            )  # fmt: skip
            await session.commit()
            return UserInfo(id=user.id, email=email, password=DEFAULT_PASSWORD, role=role)

    return _make


@pytest_asyncio.fixture
async def client_as(
    app: FastAPI, make_user: Callable[..., Awaitable[UserInfo]]
) -> AsyncIterator[Callable[..., Awaitable[httpx.AsyncClient]]]:
    """Factory: ``await client_as(Role.editor)`` → client authenticated as a fresh user of that role."""
    opened: list[httpx.AsyncClient] = []

    async def _for(role: Role = Role.viewer, *, clearance: int = 1) -> httpx.AsyncClient:
        user = await make_user(role, clearance=clearance)
        c = _client(app)
        c.headers["Authorization"] = f"Bearer {await token_for(user.email)}"
        opened.append(c)
        return c

    yield _for
    for c in opened:
        await c.aclose()


async def run_jobs(max_jobs: int = 1000) -> int:
    """Process every queued job synchronously (both queues). Returns the number of jobs processed."""
    from forge.workers.worker import Worker

    return await Worker(
        queues=["execution", "evaluation"], concurrency=1, worker_id="test-worker"
    ).run_until_idle(max_jobs=max_jobs)
