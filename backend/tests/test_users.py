"""User administration (admin only), last active admin protection."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role
from tests.conftest import token_for


def _email() -> str:
    return f"new-{uuid.uuid4().hex[:8]}@example.com"


async def test_admin_creates_lists_and_updates_users(admin_client) -> None:
    email = _email()
    created = await admin_client.post(
        "/api/v1/users",
        json={
            "email": email,
            "full_name": "Alice Martin",
            "role": "evaluator",
            "clearance": 2,
            "password": "Temporaire-123",
        },
    )
    assert created.status_code == 201, created.text
    user = created.json()
    assert user["role"] == "evaluator" and user["clearance"] == 2 and user["active"] is True
    assert "password_hash" not in user

    listing = await admin_client.get("/api/v1/users", params={"q": email, "role": "evaluator"})
    assert listing.status_code == 200, listing.text
    page = listing.json()
    assert page["total"] == 1 and page["items"][0]["id"] == user["id"] and page["page_size"] == 25

    patched = await admin_client.patch(
        f"/api/v1/users/{user['id']}", json={"role": "maintainer", "full_name": "Alice M.", "active": False}
    )
    assert patched.status_code == 200
    assert patched.json()["role"] == "maintainer" and patched.json()["active"] is False

    audit = await admin_client.get("/api/v1/audit", params={"target_id": user["id"]})
    assert {e["action"] for e in audit.json()["items"]} >= {"user.create", "user.update"}


async def test_duplicate_email_and_validation(admin_client) -> None:
    email = _email()
    body = {"email": email, "full_name": "Bob", "password": "Temporaire-123"}
    assert (await admin_client.post("/api/v1/users", json=body)).status_code == 201
    assert (
        await admin_client.post("/api/v1/users", json={**body, "email": email.upper()})
    ).status_code == 409
    assert (
        await admin_client.post("/api/v1/users", json={**body, "email": "pas-un-email"})
    ).status_code == 422
    assert (
        await admin_client.post("/api/v1/users", json={**body, "email": _email(), "password": "court"})
    ).status_code == 422


async def test_non_admin_is_forbidden(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    assert (await maintainer.get("/api/v1/users")).status_code == 403
    assert (await maintainer.post("/api/v1/users", json={})).status_code in (403, 422)


async def test_last_active_admin_cannot_be_demoted_or_deactivated(
    admin_client, make_user, db_session
) -> None:
    from sqlalchemy import select, update

    from forge.infra.models import User

    other_admin = await make_user(Role.admin)
    me = (await admin_client.get("/api/v1/auth/me")).json()
    # Deactivate every other admin so that the bootstrap admin is the last active one.
    await db_session.execute(
        update(User).where(User.role == Role.admin, User.id != uuid.UUID(me["id"])).values(active=False)
    )
    await db_session.commit()
    try:
        response = await admin_client.patch(f"/api/v1/users/{me['id']}", json={"role": "viewer"})
        assert response.status_code == 409 and "dernier administrateur" in response.json()["detail"]
        response = await admin_client.patch(f"/api/v1/users/{me['id']}", json={"active": False})
        assert response.status_code == 409
        # With a second active admin, demoting the other one is allowed.
        await admin_client.patch(f"/api/v1/users/{other_admin.id}", json={"active": True})
        demoted = await admin_client.patch(f"/api/v1/users/{other_admin.id}", json={"role": "editor"})
        assert demoted.status_code == 200
    finally:
        assert await db_session.scalar(select(User.active).where(User.id == uuid.UUID(me["id"])))


async def test_password_reset_revokes_sessions(app, admin_client, make_user) -> None:
    import httpx

    user = await make_user(Role.viewer)
    token = await token_for(user.email)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        c.headers["Authorization"] = f"Bearer {token}"
        assert (await c.get("/api/v1/auth/me")).status_code == 200
        reset = await admin_client.patch(f"/api/v1/users/{user.id}", json={"password": "Reinitialise-456"})
        assert reset.status_code == 200
        assert (await c.get("/api/v1/auth/me")).status_code == 401
