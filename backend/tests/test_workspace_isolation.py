"""Workspace isolation (ADR 001 §9, ticket NOV-105): two workspaces, every resource, three modes.

* ``enforce`` — a foreign id answers exactly like an unknown id (404, same body); lists, searches,
  exports and counters never contain foreign rows; writes and deletes on foreign ids change nothing;
  the workspace comes from the identity only (a header or a query parameter is ignored);
* ``shadow`` — the same requests are served, and every foreign row read is counted;
* ``off`` — nothing is filtered and nothing is counted (behaviour of the single-workspace platform).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from prometheus_client import REGISTRY
from sqlalchemy import delete, func, select, text, update

from forge.config import settings
from forge.domain.enums import JobKind, RunStatus
from forge.infra.db import get_sessionmaker
from forge.infra.models import (
    Agent,
    AgentVersion,
    ApiKey,
    AuditEvent,
    CompositeScore,
    DatasetItem,
    Evaluation,
    EvaluationRun,
    ExecutionTrace,
    Job,
    ProviderCredential,
    Score,
    TraceEvent,
)
from forge.infra.workspace_scope import WorkspaceViolation, bind_session
from tests.conftest import run_jobs
from tests.workspace_support import Space, client_for, create_programs, create_space


@pytest_asyncio.fixture(scope="module")
async def spaces(app: FastAPI) -> AsyncIterator[tuple[Space, Space]]:
    a, b = await create_space(), await create_space()
    previous = settings.workspace_enforcement
    settings.workspace_enforcement = "enforce"  # the programs pick their workspace's default configuration
    try:
        await create_programs(app, a)
        await create_programs(app, b)
    finally:
        settings.workspace_enforcement = previous
    yield a, b


@pytest.fixture
def enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", "enforce")


@pytest_asyncio.fixture
async def admin_a(app: FastAPI, spaces: tuple[Space, Space]) -> AsyncIterator[httpx.AsyncClient]:
    async with await client_for(app, spaces[0], "admin") as client:
        yield client


@pytest_asyncio.fixture
async def admin_b(app: FastAPI, spaces: tuple[Space, Space]) -> AsyncIterator[httpx.AsyncClient]:
    async with await client_for(app, spaces[1], "admin") as client:
        yield client


def _mask(body: dict) -> dict:
    """The body of an error, with the (necessarily different) ids of the request masked."""
    return {
        k: re.sub(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "<id>", str(v))
        for k, v in body.items()
    }


def _violations(table: str, mode: str) -> float:
    return (
        REGISTRY.get_sample_value("forge_workspace_violations_total", {"table": table, "mode": mode}) or 0.0
    )


def _fill(template: str, space: Space) -> str:
    names = {
        "agent": "agent", "agent_version": "agent_version", "scenario": "scenario",
        "scenario_version": "scenario_version", "run": "run", "dataset": "dataset", "judge": "judge",
        "config": "config", "benchmark": "benchmark_slug", "experiment": "experiment",
    }  # fmt: skip
    out = template
    for key, ref in names.items():
        out = out.replace("{" + key + "}", space.ref(ref))
    return out


# Detail routes of every resource family (read).
DETAIL_GETS = [
    "/api/v1/agents/{agent}",
    "/api/v1/agents/{agent}/versions",
    "/api/v1/agents/{agent}/health",
    "/api/v1/agent-versions/{agent_version}",
    "/api/v1/scenarios/{scenario}",
    "/api/v1/scenarios/{scenario}/versions",
    "/api/v1/scenario-versions/{scenario_version}",
    "/api/v1/datasets/{dataset}",
    "/api/v1/runs/{run}",
    "/api/v1/runs/{run}/trace",
    "/api/v1/runs/{run}/timeline",
    "/api/v1/runs/{run}/manifest",
    "/api/v1/runs/{run}/evaluations",
    "/api/v1/runs/{run}/scores",
    "/api/v1/runs/{run}/errors",
    "/api/v1/runs/{run}/feedback",
    "/api/v1/runs/{run}/risk",
    "/api/v1/runs/{run}/human-evaluations",
    "/api/v1/judges/{judge}",
    "/api/v1/evaluation-configs/{config}",
    "/api/v1/benchmarks/{benchmark}",
    "/api/v1/benchmarks/{benchmark}/executions",
    "/api/v1/benchmarks/{benchmark}/results",
    "/api/v1/experiments/{experiment}",
    "/api/v1/experiments/{experiment}/comparison",
    "/api/v1/experiments/{experiment}/gate",
]


@pytest.mark.parametrize("template", DETAIL_GETS)
async def test_foreign_id_is_indistinguishable_from_an_unknown_id(
    enforce, admin_a, spaces, template: str
) -> None:
    a, b = spaces
    own = await admin_a.get(_fill(template, a))
    assert own.status_code in (200, 404), (template, own.text)
    foreign = await admin_a.get(_fill(template, b))
    unknown_id = str(uuid.uuid4())
    unknown_path = template
    for key in ("agent_version", "scenario_version", "agent", "scenario", "dataset", "run", "judge",
                "config", "benchmark", "experiment"):  # fmt: skip
        unknown_path = unknown_path.replace("{" + key + "}", unknown_id)
    unknown = await admin_a.get(unknown_path)
    assert foreign.status_code == unknown.status_code == 404, (template, foreign.text)
    assert foreign.json() == unknown.json()


async def test_the_workspace_still_sees_its_own_resources(enforce, admin_a, spaces) -> None:
    a, _ = spaces
    readable = [
        t for t in DETAIL_GETS if not t.endswith(("/feedback", "/risk", "/comparison", "/gate", "/results"))
    ]
    for template in readable:
        response = await admin_a.get(_fill(template, a))
        assert response.status_code == 200, (template, response.text)


LISTS = [
    ("/api/v1/agents", "agent"),
    ("/api/v1/scenarios", "scenario"),
    ("/api/v1/datasets", "dataset"),
    ("/api/v1/runs", "run"),
    ("/api/v1/judges", "judge"),
    ("/api/v1/evaluation-configs", "config"),
    ("/api/v1/benchmarks", "benchmark"),
    ("/api/v1/experiments", "experiment"),
]


def _ids(payload: object) -> set[str]:
    items = payload["items"] if isinstance(payload, dict) and "items" in payload else payload
    return {str(row["id"]) for row in items}  # type: ignore[index, union-attr]


@pytest.mark.parametrize(("path", "name"), LISTS)
async def test_lists_never_contain_a_foreign_row(enforce, admin_a, spaces, path: str, name: str) -> None:
    a, b = spaces
    response = await admin_a.get(path, params={"page_size": 100})
    assert response.status_code == 200, response.text
    ids = _ids(response.json())
    assert a.ref(name) in ids and b.ref(name) not in ids


async def test_lists_of_credentials_keys_users_and_audit(enforce, admin_a, spaces) -> None:
    a, b = spaces
    credentials = {c["id"] for c in (await admin_a.get("/api/v1/credentials")).json()}
    assert a.ref("credential") in credentials and b.ref("credential") not in credentials
    keys = _ids((await admin_a.get("/api/v1/api-keys", params={"page_size": 100})).json())
    assert a.ref("api_key") in keys and b.ref("api_key") not in keys
    emails = {
        u["email"] for u in (await admin_a.get("/api/v1/users", params={"page_size": 100})).json()["items"]
    }
    assert {a.admin_email, a.editor_email} <= emails and not {b.admin_email, b.editor_email} & emails
    audit = (await admin_a.get("/api/v1/audit", params={"page_size": 100})).json()
    assert all(str(e.get("target_id")) != b.ref("run") for e in audit["items"])


async def test_search_filters_and_counters_stay_inside_the_workspace(enforce, admin_a, spaces) -> None:
    a, b = spaces
    assert (await admin_a.get("/api/v1/agents", params={"q": b.slug})).json()["total"] == 0
    assert (await admin_a.get("/api/v1/agents", params={"q": a.slug})).json()["total"] >= 1
    assert (await admin_a.get("/api/v1/scenarios", params={"q": b.slug})).json()["total"] == 0
    runs = (await admin_a.get("/api/v1/runs", params={"agent_id": b.ref("agent")})).json()
    assert runs["total"] == 0
    # Aggregates are computed on the workspace's rows only.
    dashboard = await admin_a.get("/api/v1/dashboard")
    assert dashboard.status_code == 200
    assert b.ref("run") not in dashboard.text and b.ref("agent") not in dashboard.text
    errors = await admin_a.get("/api/v1/errors")
    assert errors.status_code == 200 and b.ref("run") not in errors.text
    assert b.ref("run") not in (await admin_a.get("/api/v1/reviews/queue")).text


async def test_exports_stay_inside_the_workspace(enforce, admin_a, spaces) -> None:
    a, b = spaces
    exported = await admin_a.get("/api/v1/scenarios/export", params={"format": "json"})
    assert exported.status_code == 200
    assert f"Scénario {a.slug}" in exported.text and b.slug not in exported.text
    by_id = await admin_a.get("/api/v1/scenarios/export", params={"ids": [b.ref("scenario")]})
    assert b.slug not in by_id.text


async def test_the_other_workspace_is_symmetric(enforce, admin_b, spaces) -> None:
    a, b = spaces
    assert (await admin_b.get(f"/api/v1/agents/{a.ref('agent')}")).status_code == 404
    assert (await admin_b.get(f"/api/v1/agents/{b.ref('agent')}")).status_code == 200
    assert a.ref("agent") not in _ids((await admin_b.get("/api/v1/agents", params={"page_size": 100})).json())


async def test_the_default_workspace_and_a_new_one_do_not_see_each_other(
    enforce, admin_client, admin_b, spaces
) -> None:
    _, b = spaces
    assert (await admin_client.get(f"/api/v1/agents/{b.ref('agent')}")).status_code == 404
    assert b.ref("agent") not in _ids(
        (await admin_client.get("/api/v1/agents", params={"page_size": 100})).json()
    )
    default_agents = (await admin_client.get("/api/v1/agents", params={"page_size": 100})).json()["items"]
    if default_agents:  # data of the other tests of the session lives in the default workspace
        assert (await admin_b.get(f"/api/v1/agents/{default_agents[0]['id']}")).status_code == 404


async def test_writes_and_deletes_on_a_foreign_id_change_nothing(enforce, admin_a, admin_b, spaces) -> None:
    _, b = spaces
    attempts = [
        ("patch", f"/api/v1/agents/{b.ref('agent')}", {"description": "pirate"}),
        ("patch", f"/api/v1/scenarios/{b.ref('scenario')}", {"tags": ["pirate"]}),
        ("patch", f"/api/v1/datasets/{b.ref('dataset')}", {"description": "pirate"}),
        ("post", f"/api/v1/datasets/{b.ref('dataset')}/items", {"items": [{"key": "x", "content": "x"}]}),
        ("delete", f"/api/v1/datasets/{b.ref('dataset')}/items/{b.ref('dataset_item')}", None),
        ("delete", f"/api/v1/credentials/{b.ref('credential')}", None),
        ("patch", f"/api/v1/credentials/{b.ref('credential')}", {"description": "pirate"}),
        ("delete", f"/api/v1/api-keys/{b.ref('api_key')}", None),
        ("post", f"/api/v1/runs/{b.ref('run')}/cancel", None),
        ("post", f"/api/v1/runs/{b.ref('run')}/evaluate", {}),
        ("patch", f"/api/v1/judges/{b.ref('judge')}", {"enabled": False}),
        ("patch", f"/api/v1/benchmarks/{b.ref('benchmark')}", {"description": "pirate"}),
        ("post", f"/api/v1/benchmarks/{b.ref('benchmark')}/run", {}),
        ("post", f"/api/v1/experiments/{b.ref('experiment')}/cancel", None),
        ("patch", f"/api/v1/users/{b.editor_id}", {"active": False, "role": "viewer"}),
        ("post", f"/api/v1/agents/{b.ref('agent')}/versions", {"adapter_kind": "mock", "version": "9.9"}),
    ]
    for method, path, body in attempts:
        kwargs = {"json": body} if body is not None else {}
        response = await getattr(admin_a, method)(path, **kwargs)
        assert response.status_code == 404, (method, path, response.status_code, response.text)

    async with get_sessionmaker()() as session:
        agent = await session.get(Agent, uuid.UUID(b.ref("agent")))
        assert agent is not None and agent.description != "pirate"
        credential = await session.get(ProviderCredential, uuid.UUID(b.ref("credential")))
        assert credential is not None and credential.description != "pirate"
        key = await session.get(ApiKey, uuid.UUID(b.ref("api_key")))
        assert key is not None and key.revoked_at is None
        run = await session.get(EvaluationRun, uuid.UUID(b.ref("run")))
        assert run is not None and run.status != RunStatus.cancelled
    assert (await admin_b.get(f"/api/v1/datasets/{b.ref('dataset')}")).json()["items_count"] == 1
    assert (await admin_b.get("/api/v1/users", params={"q": b.editor_email})).json()["items"][0]["active"]


async def test_references_to_a_foreign_resource_are_refused_like_unknown_ones(
    enforce, admin_a, spaces
) -> None:
    a, b = spaces

    async def post(path: str, body: dict) -> httpx.Response:
        return await admin_a.post(path, json=body)

    cases = [
        ("/api/v1/runs", lambda v, s: {"agent_version_id": v, "scenario_ids": [s]}),
        (
            "/api/v1/experiments",
            lambda v, s: {
                "baseline_version_id": v,
                "candidate_version_id": str(uuid.uuid4()),
                "scenario_ids": [s],
            },
        ),
        (
            "/api/v1/benchmarks",
            lambda v, s: {
                "name": "Chez les autres",
                "scenarios": [{"scenario_id": s}],
                "agent_version_ids": [v],
            },
        ),
    ]
    for path, build in cases:
        foreign = await post(path, build(b.ref("agent_version"), b.ref("scenario")))
        unknown = await post(path, build(str(uuid.uuid4()), str(uuid.uuid4())))
        assert foreign.status_code == unknown.status_code, (path, foreign.text, unknown.text)
        assert foreign.status_code in (404, 422)
        assert _mask(foreign.json()) == _mask(unknown.json())
    assert not (
        await post(
            "/api/v1/runs", {"agent_version_id": a.ref("agent_version"), "scenario_ids": [b.ref("scenario")]}
        )
    ).is_success


async def test_the_workspace_comes_from_the_identity_never_from_the_request(
    enforce, app: FastAPI, spaces
) -> None:
    a, b = spaces
    async with await client_for(app, a, "key") as key_client:
        assert (await key_client.get(f"/api/v1/agents/{a.ref('agent')}")).status_code == 200
        headers = {"X-Orion-Workspace": str(b.id), "X-Orion-Project": str(b.project_id)}
        for params in ({}, {"workspace_id": str(b.id), "orion_workspace_id": str(b.id)}):
            blocked = await key_client.get(f"/api/v1/agents/{b.ref('agent')}", headers=headers, params=params)
            assert blocked.status_code == 404
            listing = await key_client.get(
                "/api/v1/agents", headers=headers, params={**params, "page_size": 100}
            )
            assert b.ref("agent") not in _ids(listing.json())
        created = await key_client.post("/api/v1/agents", headers=headers, json={"name": "Via clé"})
        assert created.status_code == 201
    async with get_sessionmaker()() as session:
        agent = await session.get(Agent, uuid.UUID(created.json()["id"]))
        # The key was issued for a project of the workspace: what it creates belongs to that project too.
        assert agent is not None and agent.workspace_id == a.id and agent.project_id == a.project_id


async def test_rows_created_through_the_api_belong_to_the_callers_workspace(
    enforce, app: FastAPI, admin_b, spaces
) -> None:
    _, b = spaces
    created = await admin_b.post("/api/v1/agents", json={"name": f"Agent API {uuid.uuid4().hex[:6]}"})
    assert created.status_code == 201
    key = await admin_b.post("/api/v1/api-keys", json={"name": "clé api", "role": "viewer"})
    assert key.status_code == 201
    async with get_sessionmaker()() as session:
        agent = await session.get(Agent, uuid.UUID(created.json()["id"]))
        assert agent is not None and agent.workspace_id == b.id
        api_key = await session.get(ApiKey, uuid.UUID(key.json()["id"]))
        assert api_key is not None and api_key.workspace_id == b.id
        events = list(
            await session.scalars(
                select(AuditEvent).where(AuditEvent.target_id.in_([created.json()["id"], key.json()["id"]]))
            )
        )
        assert len(events) == 2 and {e.workspace_id for e in events} == {b.id}
    # A project key stamps its project on what it creates.
    async with get_sessionmaker()() as session:
        bind_session(session, b.id, b.project_id)
        session.add(Agent(slug=f"projet-{uuid.uuid4().hex[:6]}", name="Agent du projet"))
        await session.flush()
        project_agent = (await session.scalars(select(Agent).order_by(Agent.created_at.desc()))).first()
        assert project_agent is not None and project_agent.project_id == b.project_id
        await session.rollback()


async def test_background_jobs_run_and_stamp_inside_their_workspace(enforce, admin_b, spaces) -> None:
    _, b = spaces
    editor_version = b.ref("agent_version")
    created = await admin_b.post(
        "/api/v1/runs", json={"agent_version_id": editor_version, "scenario_ids": [b.ref("scenario")]}
    )
    assert created.status_code == 201, created.text
    run_id = uuid.UUID(created.json()[0]["id"])
    await run_jobs()
    async with get_sessionmaker()() as session:
        run = await session.get(EvaluationRun, run_id)
        assert run is not None and run.workspace_id == b.id
        assert run.status == RunStatus.completed, (run.status, run.error)
        for model in (ExecutionTrace, TraceEvent, Evaluation, Score, CompositeScore):
            rows = list(await session.scalars(select(model).where(model.run_id == run_id)))
            assert rows and {r.workspace_id for r in rows} == {b.id}, model.__name__
        jobs = list(await session.scalars(select(Job).where(Job.run_id == run_id)))
        assert {j.kind for j in jobs} >= {JobKind.execute_run, JobKind.evaluate_run}
        assert {j.workspace_id for j in jobs} == {b.id}
        evaluate = next(j for j in jobs if j.kind == JobKind.evaluate_run)
        assert evaluate.dedupe_key == f"ws:{b.id}:evaluate_run:{run_id}"


async def test_a_row_that_slips_through_the_filter_is_refused_not_served(enforce, spaces) -> None:
    a, _ = spaces
    statement = select(Agent).from_statement(text("SELECT * FROM agents"))  # bypasses the loader criteria
    async with get_sessionmaker()() as session:
        bind_session(session, a.id)
        with pytest.raises(WorkspaceViolation):
            await session.scalars(statement)
    assert _violations("agents", "enforce") >= 1


async def test_the_filter_covers_every_statement_form(enforce, spaces) -> None:
    """Counts, column selects, joins, sub-queries, locking reads and ORM-enabled UPDATE / DELETE."""
    a, b = spaces
    async with get_sessionmaker()() as raw:  # unbound session: the platform sees every row
        expected = {
            "agents": await raw.scalar(
                text("SELECT count(*) FROM agents WHERE workspace_id = :w"), {"w": a.id}
            ),
            "with_versions": await raw.scalar(
                text("SELECT count(DISTINCT agent_id) FROM agent_versions WHERE workspace_id = :w"),
                {"w": a.id},
            ),
            "versions": await raw.scalar(
                text("SELECT count(*) FROM agent_versions WHERE workspace_id = :w"), {"w": a.id}
            ),
        }
    assert expected["agents"] and expected["versions"]
    async with get_sessionmaker()() as session:
        bind_session(session, a.id)
        assert await session.scalar(select(func.count()).select_from(Agent)) == expected["agents"]
        assert await session.scalar(select(func.count(Agent.id))) == expected["agents"]
        assert len(list(await session.scalars(select(Agent.id)))) == expected["agents"]
        assert uuid.UUID(b.ref("agent")) not in set(await session.scalars(select(Agent.id)))
        joined = select(AgentVersion.id).join(Agent, Agent.id == AgentVersion.agent_id)
        assert len(list(await session.scalars(joined))) == expected["versions"]
        in_sub = select(func.count()).select_from(Agent).where(Agent.id.in_(select(AgentVersion.agent_id)))
        assert await session.scalar(in_sub) == expected["with_versions"]
        exists = select(Agent.id).where(
            select(AgentVersion.id).where(AgentVersion.agent_id == Agent.id).exists()
        )
        assert uuid.UUID(b.ref("agent")) not in set(await session.scalars(exists))
        locked = select(Agent).where(Agent.id == uuid.UUID(b.ref("agent"))).with_for_update()
        assert await session.scalar(locked) is None
        grouped = select(AgentVersion.agent_id, func.count()).group_by(AgentVersion.agent_id)
        assert uuid.UUID(b.ref("agent")) not in {row[0] for row in (await session.execute(grouped)).all()}
        assert await session.get(Agent, uuid.UUID(b.ref("agent"))) is None
        updated = await session.execute(
            update(Agent).where(Agent.id == uuid.UUID(b.ref("agent"))).values(description="pirate")
        )
        assert updated.rowcount == 0
        deleted = await session.execute(
            delete(DatasetItem).where(DatasetItem.id == uuid.UUID(b.ref("dataset_item")))
        )
        assert deleted.rowcount == 0
        own = await session.execute(
            update(Agent).where(Agent.id == uuid.UUID(a.ref("agent"))).values(archived=False)
        )
        assert own.rowcount == 1
        await session.rollback()


async def test_workspace_id_is_immutable(spaces) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:
        agent = await session.get(Agent, uuid.UUID(a.ref("agent")))
        assert agent is not None
        agent.workspace_id = b.id
        with pytest.raises(ValueError, match="immuable"):
            await session.flush()
        await session.rollback()


# --- shadow and off ---------------------------------------------------------------------------------------


async def test_shadow_serves_everything_and_counts_foreign_reads(
    monkeypatch: pytest.MonkeyPatch, admin_a, spaces
) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", "shadow")
    a, b = spaces
    before = _violations("agents", "shadow")
    own = await admin_a.get(f"/api/v1/agents/{a.ref('agent')}")
    assert own.status_code == 200 and _violations("agents", "shadow") == before  # own rows are not counted
    foreign = await admin_a.get(f"/api/v1/agents/{b.ref('agent')}")
    assert foreign.status_code == 200 and foreign.json()["id"] == b.ref("agent")  # served, not refused
    assert _violations("agents", "shadow") == before + 1
    listing = await admin_a.get("/api/v1/agents", params={"page_size": 100})
    assert {a.ref("agent"), b.ref("agent")} <= _ids(listing.json())
    assert _violations("agents", "shadow") > before + 1
    users_before = _violations("users", "shadow")
    users = await admin_a.get("/api/v1/users", params={"page_size": 100})
    assert b.admin_email in {u["email"] for u in users.json()["items"]}
    assert _violations("users", "shadow") > users_before


async def test_shadow_counts_a_row_outside_the_workspace_but_returns_it(
    monkeypatch: pytest.MonkeyPatch, spaces
) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", "shadow")
    a, _ = spaces
    before = _violations("agents", "shadow")
    async with get_sessionmaker()() as session:
        bind_session(session, a.id)
        rows = list(await session.scalars(select(Agent).from_statement(text("SELECT * FROM agents"))))
    assert rows and _violations("agents", "shadow") > before


async def test_off_does_not_filter_and_does_not_count(
    monkeypatch: pytest.MonkeyPatch, admin_a, spaces
) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", "off")
    assert settings.workspace_enforcement == "off"
    a, b = spaces
    before = {t: _violations(t, m) for t in ("agents", "users") for m in ("shadow", "enforce")}
    assert (await admin_a.get(f"/api/v1/agents/{b.ref('agent')}")).status_code == 200
    assert {a.ref("agent"), b.ref("agent")} <= _ids(
        (await admin_a.get("/api/v1/agents", params={"page_size": 100})).json()
    )
    assert (await admin_a.get("/api/v1/users", params={"page_size": 100})).status_code == 200
    after = {t: _violations(t, m) for t in ("agents", "users") for m in ("shadow", "enforce")}
    assert after == before


def test_enforcement_defaults_to_off() -> None:
    from forge.config import Settings

    assert Settings.model_fields["workspace_enforcement"].default == "off"


@pytest.fixture(autouse=True)
def _reset_mode() -> Iterator[None]:
    previous = settings.workspace_enforcement
    yield
    settings.workspace_enforcement = previous
