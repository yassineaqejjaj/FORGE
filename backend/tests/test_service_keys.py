"""Service keys (NOV-112): attached to a workspace / project, explicit clearance, rotation, no secret in the tool."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from forge.config import settings
from forge.domain.enums import Role
from forge.infra.db import get_sessionmaker
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID, ApiKey, AuditEvent, Project
from forge.ops.__main__ import api_key_create, api_keys_list, project_move
from forge.services import api_keys as key_service
from forge.services import workspaces
from tests.conftest import _client
from tests.workspace_support import Space, client_for, create_space


@pytest_asyncio.fixture(scope="module")
async def spaces(app) -> tuple[Space, Space]:
    return await create_space(), await create_space()


async def test_existing_keys_without_attachment_stay_valid_in_the_default_workspace(admin_client) -> None:
    async with get_sessionmaker()() as session:  # created the way keys were before the workspace model
        key, plain = await key_service.create_api_key(session, None, name="avant", role=Role.viewer)
        await session.commit()
        assert key.workspace_id == ORION_DEFAULT_WORKSPACE_ID and key.project_id is None
    assert (await admin_client.get("/api/v1/agents", headers={"X-Forge-Key": plain})).status_code == 200


async def test_defaults_are_unchanged_no_explicit_fields_no_lifetime_cap(admin_client) -> None:
    created = await admin_client.post("/api/v1/api-keys", json={"name": "legacy shape"})
    assert (
        created.status_code == 201 and created.json()["role"] == "editor" and created.json()["clearance"] == 1
    )
    assert created.json()["expires_at"] is None


async def test_explicit_role_and_clearance_can_be_required(admin_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_key_require_explicit", True)
    refused = await admin_client.post("/api/v1/api-keys", json={"name": "implicite", "role": "viewer"})
    assert refused.status_code == 422 and refused.json()["code"] == "explicit_fields_required"
    assert "clearance" in refused.json()["detail"]
    ok = await admin_client.post(
        "/api/v1/api-keys", json={"name": "explicite", "role": "viewer", "clearance": 0}
    )
    assert ok.status_code == 201 and ok.json()["clearance"] == 0


async def test_a_maximum_lifetime_can_be_enforced(admin_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "api_key_max_days", 30)
    assert (await admin_client.post("/api/v1/api-keys", json={"name": "sans fin"})).status_code == 422
    far = (datetime.now(UTC) + timedelta(days=90)).isoformat()
    assert (
        await admin_client.post("/api/v1/api-keys", json={"name": "trop longue", "expires_at": far})
    ).status_code == 422
    near = (datetime.now(UTC) + timedelta(days=10)).isoformat()
    assert (
        await admin_client.post("/api/v1/api-keys", json={"name": "ok", "expires_at": near})
    ).status_code == 201


async def test_a_key_attached_to_a_workspace_is_refused_on_another_with_a_404(
    monkeypatch, app, spaces
) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", "enforce")
    a, b = spaces
    async with await client_for(app, a, "key") as key_a:
        assert (await key_a.get(f"/api/v1/agents/{a.ref('agent')}")).status_code == 200
        foreign = await key_a.get(f"/api/v1/agents/{b.ref('agent')}")
        unknown = await key_a.get(f"/api/v1/agents/{uuid.uuid4()}")
        assert foreign.status_code == unknown.status_code == 404 and foreign.json() == unknown.json()
    async with await client_for(app, a, "admin") as admin_a:  # nor can the admin of A touch B's keys
        assert (await admin_a.post(f"/api/v1/api-keys/{b.ref('api_key')}/rotate")).status_code == 404
        assert (await admin_a.delete(f"/api/v1/api-keys/{b.ref('api_key')}")).status_code == 404


async def test_a_project_key_is_attached_to_a_project_of_the_callers_workspace(
    monkeypatch, app, spaces
) -> None:
    monkeypatch.setattr(settings, "workspace_enforcement", "enforce")
    a, b = spaces
    async with await client_for(app, a, "admin") as admin_a:
        created = await admin_a.post(
            "/api/v1/api-keys", json={"name": "projet", "role": "editor", "project_id": str(a.project_id)}
        )
        assert created.status_code == 201, created.text
        foreign = await admin_a.post(
            "/api/v1/api-keys",
            json={"name": "chez l'autre", "role": "editor", "project_id": str(b.project_id)},
        )
        assert foreign.status_code == 404
    async with get_sessionmaker()() as session:
        key = await session.get(ApiKey, uuid.UUID(created.json()["id"]))
        assert key is not None and (key.workspace_id, key.project_id) == (a.id, a.project_id)
    async with _client(
        app
    ) as as_key:  # what the key creates belongs to its project, and the audit names the key
        as_key.headers["X-Forge-Key"] = created.json()["key"]
        agent = await as_key.post("/api/v1/agents", json={"name": "Par la clé"})
        assert agent.status_code == 201
    async with get_sessionmaker()() as session:
        event = await session.scalar(select(AuditEvent).where(AuditEvent.target_id == agent.json()["id"]))
        assert (
            event is not None
            and event.actor_type.value == "api_key"
            and event.actor_label == "Clé « projet »"
        )
        assert event.workspace_id == a.id


async def test_rotation_issues_an_identical_successor_and_expires_the_old_key(admin_client) -> None:
    created = (
        await admin_client.post(
            "/api/v1/api-keys",
            json={"name": "à tourner", "role": "viewer", "clearance": 2, "scopes": ["traces:write"]},
        )
    ).json()
    rotated = await admin_client.post(f"/api/v1/api-keys/{created['id']}/rotate", json={"grace_hours": 6})
    assert rotated.status_code == 201, rotated.text
    new = rotated.json()
    assert new["id"] != created["id"] and new["key"] != created["key"] and new["prefix"] != created["prefix"]
    assert (new["role"], new["clearance"], new["scopes"], new["name"]) == (
        "viewer",
        2,
        ["traces:write"],
        "à tourner",
    )
    listing = {
        i["id"]: i
        for i in (await admin_client.get("/api/v1/api-keys", params={"page_size": 100})).json()["items"]
    }
    old = listing[created["id"]]
    assert old["active"] is True and old["revoked_at"] is None  # still valid during the grace period
    assert datetime.fromisoformat(old["expires_at"]) < datetime.now(UTC) + timedelta(hours=6, minutes=1)
    headers = {"X-Forge-Key": created["key"]}
    assert (await admin_client.post("/api/v1/traces/events", headers=headers, json={})).status_code != 401
    audit = (await admin_client.get("/api/v1/audit", params={"target_id": created["id"]})).json()
    rotate = next(e for e in audit["items"] if e["action"] == "api_key.rotate")
    assert created["key"] not in json.dumps(rotate) and new["key"] not in json.dumps(rotate)


async def test_rotation_without_grace_revokes_at_once_and_refuses_a_revoked_key(admin_client) -> None:
    created = (await admin_client.post("/api/v1/api-keys", json={"name": "net", "role": "viewer"})).json()
    rotated = await admin_client.post(f"/api/v1/api-keys/{created['id']}/rotate", json={"grace_hours": 0})
    assert rotated.status_code == 201
    assert (
        await admin_client.get("/api/v1/meta", headers={"X-Forge-Key": created["key"]})
    ).status_code == 401
    assert (
        await admin_client.get("/api/v1/meta", headers={"X-Forge-Key": rotated.json()["key"]})
    ).status_code == 200
    assert (await admin_client.post(f"/api/v1/api-keys/{created['id']}/rotate")).status_code == 409
    assert (await admin_client.post(f"/api/v1/api-keys/{uuid.uuid4()}/rotate")).status_code == 404


async def test_a_project_that_leaves_its_workspace_loses_its_keys(app, spaces, monkeypatch) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:
        workspace_a = await workspaces.get_workspace(session, a.id)
        workspace_b = await workspaces.get_workspace(session, b.id)
        project = await workspaces.create_project(
            session, workspace_a, slug=f"mobile-{uuid.uuid4().hex[:5]}", name="Mobile"
        )
        _, plain = await key_service.create_api_key(
            session, None, name="clé du projet", role=Role.viewer, project_id=project.id, workspace_id=a.id
        )
        await session.commit()
        project_id = project.id
    async with _client(app) as client:
        assert (await client.get("/api/v1/meta", headers={"X-Forge-Key": plain})).status_code == 200
        async with get_sessionmaker()() as session:  # the guard alone, before any revocation: a moved project
            await session.execute(
                text("UPDATE projects SET workspace_id = :w WHERE id = :p"), {"w": b.id, "p": project_id}
            )
            await session.commit()
        refused = await client.get("/api/v1/meta", headers={"X-Forge-Key": plain})
        assert refused.status_code == 401
        async with get_sessionmaker()() as session:
            await session.execute(
                text("UPDATE projects SET workspace_id = :w WHERE id = :p"), {"w": a.id, "p": project_id}
            )
            await session.commit()
        assert (await client.get("/api/v1/meta", headers={"X-Forge-Key": plain})).status_code == 200
    async with get_sessionmaker()() as session:
        project = await session.get(Project, project_id)
        workspace_b = await workspaces.get_workspace(session, b.id)
        assert project is not None
        assert await workspaces.move_project(session, None, project, workspace_b) == 1  # service: revokes
        await session.commit()
        revoked = await session.scalar(select(ApiKey.revoked_at).where(ApiKey.project_id == project_id))
        assert revoked is not None
    async with _client(app) as client:
        assert (await client.get("/api/v1/meta", headers={"X-Forge-Key": plain})).status_code == 401


async def test_a_project_that_still_holds_resources_cannot_move(spaces) -> None:
    a, b = spaces
    async with get_sessionmaker()() as session:
        workspace_a = await workspaces.get_workspace(session, a.id)
        workspace_b = await workspaces.get_workspace(session, b.id)
        project = await workspaces.create_project(
            session, workspace_a, slug=f"plein-{uuid.uuid4().hex[:5]}", name="Plein"
        )
        await session.execute(
            text("UPDATE agents SET project_id = :p WHERE id = :a"),
            {"p": project.id, "a": uuid.UUID(a.ref("agent"))},
        )
        with pytest.raises(Exception, match="ressources"):
            await workspaces.move_project(session, None, project, workspace_b)
        await session.rollback()


async def test_the_admin_tool_lists_keys_by_workspace_and_project_without_any_secret(
    spaces, capsys: pytest.CaptureFixture[str]
) -> None:
    a, _ = spaces
    assert await api_keys_list(a.slug, None, as_json=True) == 0
    out = capsys.readouterr().out
    rows = json.loads(out)
    assert rows and {r["workspace"] for r in rows} == {a.slug}
    for row in rows:
        assert row["key"].startswith("fgk_") and row["key"].endswith("••••")
        assert {"age_days", "last_used_at", "expires_at", "status", "role", "clearance"} <= set(row)
    async with get_sessionmaker()() as session:
        hashes = list(await session.scalars(select(ApiKey.key_hash)))
    assert not any(h in out for h in hashes)
    assert await api_keys_list(None, "projet", as_json=False) == 0
    assert "aucun secret affiché" in capsys.readouterr().out


async def test_the_admin_tool_creates_a_project_key_and_shows_it_once(
    spaces, capsys: pytest.CaptureFixture[str]
) -> None:
    a, _ = spaces
    assert await api_key_create(a.slug, "projet", "clé ops", "viewer", 1, 30) == 0
    created = capsys.readouterr().out
    plain = next(w for w in created.split() if w.startswith("fgk_"))
    async with get_sessionmaker()() as session:
        key = await session.scalar(
            select(ApiKey).where(ApiKey.name == "clé ops", ApiKey.workspace_id == a.id)
        )
        assert key is not None and key.project_id == a.project_id and key.expires_at is not None
        assert plain not in key.key_hash
    assert await api_key_create(a.slug, "inconnu", "x", "viewer", 1, None) == 2
    await api_keys_list(a.slug, None, as_json=False)
    assert plain not in capsys.readouterr().out  # listed afterwards: masked only
    assert await project_move("inconnu", a.slug, a.slug) == 2
