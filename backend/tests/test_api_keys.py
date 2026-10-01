"""Service API keys: shown once, masked, scoped, revocable."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from forge.domain.enums import Role


async def test_create_key_is_shown_once_and_authenticates(admin_client) -> None:
    created = await admin_client.post(
        "/api/v1/api-keys", json={"name": "Pipeline CI", "role": "editor", "clearance": 2}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    key = body["key"]
    assert key.startswith(f"fgk_{body['prefix']}_") and body["masked_key"].endswith("••••")
    assert body["active"] is True and body["scopes"] == []

    listing = await admin_client.get("/api/v1/api-keys")
    item = next(i for i in listing.json()["items"] if i["id"] == body["id"])
    assert "key" not in item and item["masked_key"] == body["masked_key"]

    response = await admin_client.get("/api/v1/agents", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    response = await admin_client.get("/api/v1/agents", headers={"X-Forge-Key": key, "Authorization": ""})
    assert response.status_code == 200


async def test_scoped_key_can_only_push_traces(admin_client) -> None:
    created = await admin_client.post(
        "/api/v1/api-keys", json={"name": "Agent traces", "role": "editor", "scopes": ["traces:write"]}
    )
    key = created.json()["key"]
    response = await admin_client.get("/api/v1/agents", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 403
    assert (
        await admin_client.post("/api/v1/api-keys", json={"name": "x", "scopes": ["admin"]})
    ).status_code == 422


async def test_revoke_key(admin_client) -> None:
    created = (await admin_client.post("/api/v1/api-keys", json={"name": "Temp", "role": "viewer"})).json()
    assert (await admin_client.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 204
    assert (await admin_client.delete(f"/api/v1/api-keys/{created['id']}")).status_code == 409
    response = await admin_client.get("/api/v1/meta", headers={"Authorization": f"Bearer {created['key']}"})
    assert response.status_code == 401
    listing = (await admin_client.get("/api/v1/api-keys", params={"include_revoked": False})).json()
    assert created["id"] not in {i["id"] for i in listing["items"]}
    audit = (await admin_client.get("/api/v1/audit", params={"target_id": created["id"]})).json()
    assert {e["action"] for e in audit["items"]} == {"api_key.create", "api_key.revoke"}


async def test_expiration_validation_and_admin_only(admin_client, client_as) -> None:
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (
        await admin_client.post("/api/v1/api-keys", json={"name": "old", "expires_at": past})
    ).status_code == 422
    future = (datetime.now(UTC) + timedelta(days=30)).isoformat()
    created = await admin_client.post("/api/v1/api-keys", json={"name": "soon", "expires_at": future})
    assert created.status_code == 201 and created.json()["expires_at"]
    maintainer = await client_as(Role.maintainer)
    assert (await maintainer.get("/api/v1/api-keys")).status_code == 403
