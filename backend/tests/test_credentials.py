"""Provider credentials: secrets never returned, rotation, deletion refused when referenced."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role
from forge.services.credentials import resolve_credentials


def _name() -> str:
    return f"cred-{uuid.uuid4().hex[:8]}"


async def test_create_list_rotate_delete(admin_client, db_session) -> None:
    name = _name()
    created = await admin_client.post(
        "/api/v1/credentials",
        json={
            "name": name,
            "kind": "openai",
            "secret": "sk-test-1234567890abcd",
            "headers": {"X-Org": "forge"},
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret_hint"] == "••••abcd" and body["has_secret"] and body["has_headers"]
    assert "sk-test" not in created.text and "forge" not in str(body.get("headers"))
    assert (
        await admin_client.post("/api/v1/credentials", json={"name": name, "kind": "http"})
    ).status_code == 409

    listing = await admin_client.get("/api/v1/credentials")
    assert any(c["id"] == body["id"] for c in listing.json()) and "sk-test" not in listing.text

    rotated = await admin_client.patch(
        f"/api/v1/credentials/{body['id']}",
        json={"secret": "sk-new-secret-zzzz9999", "description": "Rotation"},
    )
    assert rotated.status_code == 200
    assert rotated.json()["secret_hint"] == "••••9999" and rotated.json()["rotated_at"]
    secrets = await resolve_credentials(db_session, body["id"])
    assert secrets["api_key"] == "sk-new-secret-zzzz9999" and secrets["header:X-Org"] == "forge"

    assert (await admin_client.delete(f"/api/v1/credentials/{body['id']}")).status_code == 204
    assert (await admin_client.delete(f"/api/v1/credentials/{body['id']}")).status_code == 404


async def test_delete_refused_when_referenced_by_agent_version(admin_client) -> None:
    cred = (
        await admin_client.post(
            "/api/v1/credentials", json={"name": _name(), "kind": "http", "secret": "tok-123456789"}
        )
    ).json()
    agent = (await admin_client.post("/api/v1/agents", json={"name": f"Agent {uuid.uuid4().hex[:6]}"})).json()
    version = await admin_client.post(
        f"/api/v1/agents/{agent['id']}/versions",
        json={
            "adapter_kind": "custom_api",
            "endpoint": "https://agent.example.com/run",
            "credential_id": cred["id"],
        },
    )
    assert version.status_code == 201, version.text
    assert version.json()["credential"]["secret_hint"] == "••••6789"
    response = await admin_client.delete(f"/api/v1/credentials/{cred['id']}")
    assert response.status_code == 409 and "1 version(s)" in response.json()["detail"]
    listed = next(c for c in (await admin_client.get("/api/v1/credentials")).json() if c["id"] == cred["id"])
    assert listed["agent_versions_count"] == 1


async def test_credentials_writes_are_admin_only(client_as) -> None:
    editor = await client_as(Role.editor)
    assert (await editor.get("/api/v1/credentials")).status_code == 403
    maintainer = await client_as(Role.maintainer)
    listed = await maintainer.get("/api/v1/credentials")  # needed to pin credentials on judges
    assert listed.status_code == 200
    assert all("secret" not in c or c["secret"] is None for c in listed.json())
    created = await maintainer.post("/api/v1/credentials", json={"name": "x", "kind": "openai", "secret": "sk-x"})
    assert created.status_code == 403
