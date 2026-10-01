"""Authentication: real login endpoint, session cookie, rate limit, logout, password change."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from forge.domain.enums import Role
from forge.infra.models import AuditEvent, User
from forge.infra.security import SESSION_COOKIE_NAME
from tests.conftest import DEFAULT_PASSWORD


async def test_login_sets_http_only_cookie_and_returns_user(client, make_user) -> None:
    user = await make_user(Role.editor, clearance=2)
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email.upper(), "password": user.password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token"] is None
    assert body["user"]["email"] == user.email and body["user"]["role"] == "editor"
    assert body["user"]["clearance"] == 2 and body["user"]["last_login_at"]
    assert set(body["user"]) >= {"id", "full_name", "avatar_color", "active", "created_at"}
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE_NAME in cookie and "httponly" in cookie.lower() and "samesite=lax" in cookie.lower()
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["email"] == user.email


async def test_login_can_return_token_for_cli(app, make_user) -> None:
    import httpx

    user = await make_user(Role.viewer)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        response = await c.post(
            "/api/v1/auth/login", json={"email": user.email, "password": user.password, "return_token": True}
        )
        token = response.json()["token"]
        assert token
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        me = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200


async def test_wrong_password_is_rejected_and_audited(client, make_user, db_session) -> None:
    user = await make_user(Role.viewer)
    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": "mauvais-mot"})
    assert response.status_code == 401
    assert response.json() == {"detail": "E-mail ou mot de passe incorrect", "code": "unauthorized"}
    unknown = await client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert unknown.status_code == 401
    events = list(
        await db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "auth.login_failed", AuditEvent.target_id == str(user.id)
            )
        )
    )
    assert events and events[0].details["email"] == user.email


async def test_successful_login_is_audited(client, make_user, db_session) -> None:
    user = await make_user(Role.viewer)
    await client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    assert await db_session.scalar(
        select(AuditEvent.id).where(AuditEvent.action == "auth.login", AuditEvent.target_id == str(user.id))
    )


async def test_login_is_rate_limited_per_email_and_ip(client) -> None:
    from forge.config import settings

    email = f"brute-{uuid.uuid4().hex[:8]}@example.com"
    statuses = [
        (await client.post("/api/v1/auth/login", json={"email": email, "password": "x"})).status_code
        for _ in range(settings.login_rate_limit_per_minute + 2)
    ]
    assert statuses[: settings.login_rate_limit_per_minute] == [401] * settings.login_rate_limit_per_minute
    assert statuses[-1] == 429
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": "x"})
    assert response.json()["code"] == "rate_limited" and "Trop de tentatives" in response.json()["detail"]


async def test_inactive_user_cannot_log_in(client, make_user, db_session) -> None:
    user = await make_user(Role.viewer)
    row = await db_session.get(User, user.id)
    row.active = False
    await db_session.commit()
    response = await client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    assert response.status_code == 403


async def test_logout_clears_cookie(client, make_user) -> None:
    user = await make_user(Role.viewer)
    await client.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
    response = await client.post("/api/v1/auth/logout")
    assert response.status_code == 204
    assert SESSION_COOKIE_NAME in response.headers["set-cookie"]
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_password_change_revokes_other_sessions(app, make_user) -> None:
    import httpx

    user = await make_user(Role.editor)

    def new_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async with new_client() as first, new_client() as second:
        await first.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
        await second.post("/api/v1/auth/login", json={"email": user.email, "password": user.password})
        bad = await first.post(
            "/api/v1/auth/password", json={"current_password": "faux-mot-de-passe", "new_password": "x" * 12}
        )
        assert bad.status_code == 400
        short = await first.post(
            "/api/v1/auth/password", json={"current_password": DEFAULT_PASSWORD, "new_password": "court"}
        )
        assert short.status_code == 422
        changed = await first.post(
            "/api/v1/auth/password",
            json={"current_password": DEFAULT_PASSWORD, "new_password": "Nouveau-mot-de-passe-1"},
        )
        assert changed.status_code == 200, changed.text
        assert (await first.get("/api/v1/auth/me")).status_code == 200  # new cookie
        revoked = await second.get("/api/v1/auth/me")
        assert revoked.status_code == 401 and "révoquée" in revoked.json()["detail"]
    async with new_client() as third:
        ok = await third.post(
            "/api/v1/auth/login", json={"email": user.email, "password": "Nouveau-mot-de-passe-1"}
        )
        assert ok.status_code == 200


async def test_api_key_cannot_use_me(admin_client) -> None:
    created = await admin_client.post("/api/v1/api-keys", json={"name": "ci", "role": "viewer"})
    key = created.json()["key"]
    response = await admin_client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 403
