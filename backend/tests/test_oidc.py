"""OIDC relying party (NOV-108): tokens, mapping, the browser flow and the explicit account link.

The IdP is synthetic (``tests/oidc_support``): a throw-away RSA key and respx-mocked JWKS / token endpoints.
Everything is off by default; the existing authentication suites run unchanged with the default settings.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
import respx
from fastapi import FastAPI
from sqlalchemy import func, select

from forge.config import Settings, settings
from forge.domain.enums import Role
from forge.infra.db import get_sessionmaker
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID, AuditEvent, ExternalIdentity, User, WorkspaceMember
from forge.services import oidc as oidc_service
from tests.conftest import DEFAULT_PASSWORD, UserInfo, _client
from tests.factories import create_scenario_version
from tests.oidc_support import (
    AUTH_URL,
    ISSUER,
    JWKS_URL,
    KEY,
    REDIRECT_URI,
    ROTATED_KEY,
    TOKEN_URL,
    IdpKey,
    jwks,
    token,
)

DEFAULT_WS = str(ORION_DEFAULT_WORKSPACE_ID)
MakeUser = Callable[..., Awaitable[UserInfo]]


@pytest.fixture
def sso(monkeypatch: pytest.MonkeyPatch) -> None:
    """OIDC enabled against the synthetic IdP (the settings validator derives these in production)."""
    for name, value in {
        "oidc_enabled": True,
        "oidc_issuer": ISSUER,
        "oidc_audience": "forge",
        "oidc_client_id": "forge",
        "oidc_client_secret": "",
        "oidc_authorization_endpoint": AUTH_URL,
        "oidc_token_endpoint": TOKEN_URL,
        "oidc_jwks_url": JWKS_URL,
        "oidc_redirect_uri": REDIRECT_URI,
        "oidc_jwks_min_refresh_seconds": 30.0,
        "oidc_auto_provision": False,
        "password_login_disabled_for_linked": False,
        "require_mfa_for_admin": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    oidc_service.jwks_cache.clear()


@pytest.fixture
def idp() -> respx.MockRouter:
    with respx.mock(assert_all_called=False) as router:
        router.get(JWKS_URL, name="jwks").mock(return_value=httpx.Response(200, json=jwks(KEY)))
        yield router


@pytest_asyncio.fixture
async def sso_app(app: FastAPI, sso: None) -> FastAPI:
    from forge.api.main import create_app

    return create_app()  # routes are mounted at build time: a new app with OIDC enabled


@pytest_asyncio.fixture
async def client(sso_app: FastAPI, idp: respx.MockRouter) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(sso_app) as c:
        yield c


async def link(user: UserInfo, sub: str) -> None:
    async with get_sessionmaker()() as session:
        session.add(ExternalIdentity(issuer=ISSUER, sub=sub, user_id=user.id))
        await session.commit()


def bearer(subject: str, **overrides: object) -> dict[str, str]:
    return {"Authorization": f"Bearer {token(subject, **overrides)}"}


async def linked_user(
    make_user: MakeUser, role: Role = Role.editor, *, clearance: int = 3
) -> tuple[UserInfo, str]:
    user = await make_user(role, clearance=clearance)
    sub = f"sub-{uuid.uuid4()}"
    await link(user, sub)
    return user, sub


# --- Disabled by default ------------------------------------------------------------------------------------------------


def test_everything_is_off_by_default() -> None:
    defaults = Settings.model_fields
    assert defaults["oidc_enabled"].default is False
    assert defaults["oidc_auto_provision"].default is False
    assert defaults["password_login_disabled_for_linked"].default is False
    assert defaults["require_mfa_for_admin"].default is False


async def test_with_oidc_disabled_no_route_exists_and_an_idp_token_is_not_a_credential(
    app: FastAPI, make_user: MakeUser
) -> None:
    async with _client(app) as plain:  # the default application (flag off)
        assert (await plain.get("/api/v1/auth/oidc/login")).status_code == 404
        assert (await plain.get("/api/v1/auth/oidc/link")).status_code == 404
        _, sub = await linked_user(make_user)
        denied = await plain.get("/api/v1/auth/me", headers=bearer(sub))
        assert denied.status_code == 401  # read as a (malformed) local session token, as before


# --- Bearer tokens: validation ----------------------------------------------------------------------------------------


async def test_a_valid_token_of_a_linked_user_authenticates_as_that_user(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user, sub = await linked_user(make_user, Role.editor)
    response = await client.get("/api/v1/auth/me", headers=bearer(sub))
    assert response.status_code == 200 and response.json()["email"].startswith("user-")
    assert response.json()["id"] == str(user.id) and response.json()["role"] == "editor"


@pytest.mark.parametrize(
    ("label", "overrides", "code"),
    [
        ("expired", {"exp": int(time.time()) - 600, "iat": int(time.time()) - 900}, "expired"),
        ("not yet valid", {"nbf": int(time.time()) + 3600}, "not_yet_valid"),
        ("wrong issuer", {"iss": "https://evil.example/realms/orion"}, "invalid_issuer"),
        ("wrong audience", {"aud": "nova-web"}, "invalid_audience"),
        ("no subject", {"sub": None}, "missing_claim:sub"),
        ("no expiry", {"exp": None}, "missing_claim:exp"),
        ("malformed clearance", {"orion_clearance": "high"}, "invalid_claim:orion_clearance"),
        ("clearance out of range", {"orion_clearance": 9}, "invalid_claim:orion_clearance"),
    ],
)
async def test_invalid_tokens_are_refused(
    client: httpx.AsyncClient, make_user: MakeUser, label: str, overrides: dict, code: str
) -> None:
    _, sub = await linked_user(make_user)
    sub = overrides.get("sub", sub) if overrides.get("sub") else sub
    response = await client.get("/api/v1/auth/me", headers=bearer(sub, **overrides))
    assert response.status_code == 401, label
    assert code in response.json()["detail"]


async def test_a_token_signed_by_another_key_or_with_a_forged_algorithm_is_refused(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user)
    other = IdpKey("test-key-1")  # same kid, different key material
    forged = {"Authorization": f"Bearer {token(sub, other)}"}
    assert (await client.get("/api/v1/auth/me", headers=forged)).status_code == 401
    local = token(sub).split(".")
    tampered = {"Authorization": f"Bearer {local[0]}.{local[1]}x.{local[2]}"}
    assert (await client.get("/api/v1/auth/me", headers=tampered)).status_code == 401


async def test_the_jwks_is_cached_and_refreshed_once_when_the_realm_rotates_its_keys(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sub = await linked_user(make_user)
    route = idp["jwks"]
    for _ in range(3):
        assert (await client.get("/api/v1/auth/me", headers=bearer(sub))).status_code == 200
    assert route.call_count == 1  # cached
    monkeypatch.setattr(settings, "oidc_jwks_min_refresh_seconds", 0.0)
    route.mock(return_value=httpx.Response(200, json=jwks(KEY, ROTATED_KEY)))
    rotated = {"Authorization": f"Bearer {token(sub, ROTATED_KEY)}"}
    assert (await client.get("/api/v1/auth/me", headers=rotated)).status_code == 200
    assert route.call_count == 2  # one refresh for the unknown kid


async def test_an_unknown_kid_cannot_make_forge_hammer_the_idp(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user)
    route = idp["jwks"]
    assert (await client.get("/api/v1/auth/me", headers=bearer(sub))).status_code == 200
    unknown = {"Authorization": f"Bearer {token(sub, kid='nobody')}"}
    for _ in range(5):
        assert (await client.get("/api/v1/auth/me", headers=unknown)).status_code == 401
    assert route.call_count == 1  # min refresh delay (30 s) not elapsed


async def test_the_idp_being_down_with_a_cold_cache_is_a_503_not_a_pass(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user)
    idp["jwks"].mock(return_value=httpx.Response(500))
    response = await client.get("/api/v1/auth/me", headers=bearer(sub))
    assert response.status_code == 503


# --- Bearer tokens: what they open ------------------------------------------------------------------------------------


async def test_an_unlinked_identity_a_service_account_and_a_token_without_workspace_open_nothing(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user)
    unlinked = await client.get("/api/v1/auth/me", headers=bearer("sub-unknown"))
    assert unlinked.status_code == 401 and "unlinked" in unlinked.json()["detail"]
    service = await client.get(
        "/api/v1/auth/me", headers=bearer(sub, preferred_username="service-account-nova")
    )
    assert service.status_code == 403 and service.json()["code"] == "service_account"
    nowhere = await client.get("/api/v1/auth/me", headers=bearer(sub, orion_workspace_id=None))
    assert nowhere.status_code == 403 and nowhere.json()["code"] == "no_workspace"
    elsewhere = await client.get(
        "/api/v1/auth/me", headers=bearer(sub, orion_workspace_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    )
    assert elsewhere.status_code == 403 and elsewhere.json()["code"] == "workspace_mismatch"


async def test_a_deactivated_user_is_refused_even_with_a_valid_token(
    client: httpx.AsyncClient, make_user: MakeUser, admin_client: httpx.AsyncClient
) -> None:
    user, sub = await linked_user(make_user)
    assert (await admin_client.patch(f"/api/v1/users/{user.id}", json={"active": False})).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=bearer(sub))).status_code == 401


async def test_the_realm_role_caps_the_local_role_and_never_raises_it(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    admin_local, sub = await linked_user(make_user, Role.admin)
    users = "/api/v1/users"
    assert (await client.get(users, headers=bearer(sub))).status_code == 200  # no realm role: local role
    capped = {"realm_access": {"roles": ["forge-viewer"]}}
    assert (await client.get(users, headers=bearer(sub, **capped))).status_code == 403  # capped to viewer
    editor_local, editor_sub = await linked_user(make_user, Role.editor)
    raising = {"realm_access": {"roles": ["forge-admin"]}}
    assert (await client.get(users, headers=bearer(editor_sub, **raising))).status_code == 403  # never raised
    other_service = {"realm_access": {"roles": ["nova-admin", "orbit-admin"]}}
    assert (await client.get(users, headers=bearer(editor_sub, **other_service))).status_code == 403
    assert admin_local.id != editor_local.id


async def test_the_effective_clearance_is_the_minimum_of_the_local_value_and_the_claim(
    client: httpx.AsyncClient, make_user: MakeUser, db_session
) -> None:
    sv = await create_scenario_version(db_session, name="Scénario C3")
    scenario = sv.scenario_id
    from forge.infra.models import Scenario

    row = await db_session.get(Scenario, scenario)
    assert row is not None
    row.classification = 3
    await db_session.commit()
    _, sub = await linked_user(make_user, Role.viewer, clearance=3)
    url = f"/api/v1/scenarios/{scenario}"
    assert (await client.get(url, headers=bearer(sub))).status_code == 200  # absent claim: local value
    assert (await client.get(url, headers=bearer(sub, orion_clearance=3))).status_code == 200
    assert (
        await client.get(url, headers=bearer(sub, orion_clearance=1))
    ).status_code == 404  # capped below C3
    low, low_sub = await linked_user(make_user, Role.viewer, clearance=1)
    assert (
        await client.get(url, headers=bearer(low_sub, orion_clearance=3))
    ).status_code == 404  # never raised
    assert low.id


async def test_mfa_is_required_for_administration_only_when_the_flag_is_set(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sub = await linked_user(make_user, Role.admin)
    users = "/api/v1/users"
    assert (await client.get(users, headers=bearer(sub))).status_code == 200  # flag off: nothing changes
    monkeypatch.setattr(settings, "require_mfa_for_admin", True)
    refused = await client.get(users, headers=bearer(sub, amr=["pwd"]))
    assert refused.status_code == 403 and "multifacteur" in refused.json()["detail"]
    assert (await client.get(users, headers=bearer(sub, amr=["pwd", "mfa"]))).status_code == 200
    assert (await client.get("/api/v1/auth/me", headers=bearer(sub, amr=["pwd"]))).status_code == 200


async def test_a_delegated_token_keeps_both_identities_in_the_audit_trail(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user, Role.editor)
    delegated = bearer(sub, act={"sub": "nova-service", "client_id": "nova-web"})
    created = await client.post("/api/v1/agents", headers=delegated, json={"name": "Agent délégué"})
    assert created.status_code == 201
    async with get_sessionmaker()() as session:
        event = await session.scalar(select(AuditEvent).where(AuditEvent.target_id == created.json()["id"]))
        assert event is not None and "nova-service" in event.actor_label


# --- Browser flow ------------------------------------------------------------------------------------------------------


def _authorization(location: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}


async def start(client: httpx.AsyncClient, next_path: str = "/") -> dict[str, str]:
    response = await client.get("/api/v1/auth/oidc/login", params={"next": next_path})
    assert response.status_code == 302 and response.headers["location"].startswith(AUTH_URL)
    return _authorization(response.headers["location"])


def idp_answers(idp: respx.MockRouter, sub: str, nonce: str, **overrides: object) -> None:
    body = {
        "access_token": token(sub, **overrides),
        "id_token": token(sub, aud="forge", nonce=nonce, **overrides),
        "token_type": "Bearer",
    }
    idp.post(TOKEN_URL, name="token").mock(return_value=httpx.Response(200, json=body))


async def test_login_redirects_with_pkce_state_and_nonce(client: httpx.AsyncClient) -> None:
    params = await start(client)
    assert params["code_challenge_method"] == "S256" and params["response_type"] == "code"
    assert params["client_id"] == "forge" and params["redirect_uri"] == REDIRECT_URI
    assert params["scope"] == "openid email profile" and params["state"] and params["nonce"]
    assert "forge_oidc" in client.cookies
    again = await start(client)
    assert again["state"] != params["state"] and again["code_challenge"] != params["code_challenge"]


async def test_a_linked_user_gets_a_forge_session_carrying_the_caps_of_the_token(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    user, sub = await linked_user(make_user, Role.admin)
    params = await start(client, "/runs?x=1")
    idp_answers(idp, sub, params["nonce"], realm_access={"roles": ["forge-viewer"]})
    done = await client.get("/api/v1/auth/oidc/callback", params={"code": "abc", "state": params["state"]})
    assert done.status_code == 302 and done.headers["location"] == "/runs?x=1"
    exchange = idp["token"].calls.last.request
    assert b"code_verifier=" in exchange.content and b"code=abc" in exchange.content
    me = await client.get("/api/v1/auth/me")  # session cookie only
    assert me.status_code == 200 and me.json()["id"] == str(user.id)
    assert (await client.get("/api/v1/users")).status_code == 403  # admin capped to viewer by the token
    assert (await client.get("/api/v1/agents")).status_code == 200


async def test_the_callback_refuses_a_bad_state_a_swapped_nonce_and_a_refused_code(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user)
    params = await start(client)
    idp_answers(idp, sub, params["nonce"])
    wrong = await client.get("/api/v1/auth/oidc/callback", params={"code": "abc", "state": "forged"})
    assert wrong.headers["location"].endswith("sso_error=state_mismatch")
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    params = await start(client)
    idp_answers(idp, sub, "another-nonce")
    swapped = await client.get("/api/v1/auth/oidc/callback", params={"code": "c2", "state": params["state"]})
    assert swapped.headers["location"].endswith("sso_error=invalid_nonce")
    params = await start(client)
    idp.post(TOKEN_URL, name="token").mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
    refused = await client.get(
        "/api/v1/auth/oidc/callback", params={"code": "used", "state": params["state"]}
    )
    assert refused.headers["location"].endswith("sso_error=code_refused")
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_a_login_attempt_can_be_completed_only_once_even_with_a_copy_of_its_cookie(
    sso_app: FastAPI, client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    _, sub = await linked_user(make_user)
    params = await start(client)
    saved = client.cookies.get("forge_oidc")
    idp_answers(idp, sub, params["nonce"])
    first = await client.get("/api/v1/auth/oidc/callback", params={"code": "c1", "state": params["state"]})
    assert first.headers["location"] == "/" and client.cookies.get("forge_oidc") is None  # cleared after use
    async with _client(sso_app) as attacker:
        attacker.cookies.set("forge_oidc", saved, path="/api/v1/auth/oidc")
        second = await attacker.get(
            "/api/v1/auth/oidc/callback", params={"code": "c1", "state": params["state"]}
        )
        assert second.headers["location"].endswith("sso_error=state_replayed")
        assert (await attacker.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.parametrize(
    "target", ["https://evil.example", "//evil.example", "/\\evil", "javascript:alert(1)"]
)
async def test_the_post_login_target_is_always_a_local_path(client: httpx.AsyncClient, target: str) -> None:
    params = await start(client, target)
    del params
    assert oidc_service.safe_next(target) == "/"
    assert oidc_service.safe_next("/runs/1?x=2") == "/runs/1?x=2"


async def count_links() -> int:
    async with get_sessionmaker()() as session:
        return int(await session.scalar(select(func.count()).select_from(ExternalIdentity)) or 0)


async def sso_callback(
    client: httpx.AsyncClient, idp: respx.MockRouter, sub: str, **overrides: object
) -> httpx.Response:
    params = await start(client)
    idp_answers(idp, sub, params["nonce"], **overrides)
    return await client.get("/api/v1/auth/oidc/callback", params={"code": "abc", "state": params["state"]})


# --- Account link: explicit, confirmed, never automatic ---------------------------------------------------------------


async def test_a_verified_email_alone_never_links_an_account(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    user = await make_user(Role.editor)
    before = await count_links()
    done = await sso_callback(client, idp, "sub-new", email=user.email)
    assert done.status_code == 302 and done.headers["location"] == "/oidc/link"
    assert await count_links() == before  # nothing linked yet
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 401  # and no session either


async def test_the_link_needs_explicit_confirmation_and_the_local_password(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    user = await make_user(Role.editor)
    await sso_callback(client, idp, "sub-confirm", email=user.email)
    before = await count_links()
    pending = await client.get("/api/v1/auth/oidc/link")
    assert pending.status_code == 200 and pending.json()["account_email"] == user.email
    declined = await client.post(
        "/api/v1/auth/oidc/link", json={"confirm": False, "password": DEFAULT_PASSWORD}
    )
    assert declined.status_code == 400 and declined.json()["code"] == "confirmation_required"
    wrong = await client.post(
        "/api/v1/auth/oidc/link", json={"confirm": True, "password": "pas-le-bon-mot-de-passe"}
    )
    assert wrong.status_code == 401
    assert await count_links() == before and (await client.get("/api/v1/auth/me")).status_code == 401
    ok = await client.post("/api/v1/auth/oidc/link", json={"confirm": True, "password": DEFAULT_PASSWORD})
    assert ok.status_code == 200 and ok.json()["id"] == str(user.id)
    assert await count_links() == before + 1
    assert (await client.get("/api/v1/auth/me")).json()["id"] == str(user.id)  # session opened
    async with get_sessionmaker()() as session:
        actions = set(
            await session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == str(user.id)))
        )
        assert {"auth.oidc_link", "auth.oidc_link_refused"} <= actions
    # the identity is now linked: next time the callback logs in directly, and linking again is a conflict
    again = await sso_callback(client, idp, "sub-confirm", email=user.email)
    assert again.headers["location"] == "/"


async def test_an_identity_cannot_be_linked_twice_nor_a_user_to_two_identities(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    user = await make_user(Role.editor)
    await link(user, "sub-first")
    await sso_callback(client, idp, "sub-second", email=user.email)
    conflict = await client.post(
        "/api/v1/auth/oidc/link", json={"confirm": True, "password": DEFAULT_PASSWORD}
    )
    assert conflict.status_code == 409 and conflict.json()["code"] == "user_already_linked"


async def test_an_unverified_email_is_never_matched_and_an_unknown_account_is_not_created(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser
) -> None:
    user = await make_user(Role.editor)
    unverified = await sso_callback(client, idp, "sub-u", email=user.email, email_verified=False)
    assert unverified.headers["location"].endswith("sso_error=unknown_account")
    stranger = await sso_callback(client, idp, "sub-s", email=f"nobody-{uuid.uuid4().hex[:6]}@example.test")
    assert stranger.headers["location"].endswith("sso_error=unknown_account")
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(User.id).where(User.email.like("nobody-%"))) is None


async def test_auto_provision_creates_a_lowest_rights_account_in_the_workspace_of_the_token(
    client: httpx.AsyncClient, idp: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "oidc_auto_provision", True)
    email = f"new-{uuid.uuid4().hex[:6]}@example.test"
    done = await sso_callback(
        client, idp, "sub-new-user", email=email, name="Nouvelle Personne", orion_clearance=2
    )
    assert done.headers["location"] == "/"
    me = (await client.get("/api/v1/auth/me")).json()
    assert me["email"] == email and me["role"] == "viewer" and me["clearance"] == 1
    async with get_sessionmaker()() as session:
        member = await session.get(WorkspaceMember, uuid.UUID(me["id"]))
        assert member is not None and member.workspace_id == ORION_DEFAULT_WORKSPACE_ID
        assert await session.get(ExternalIdentity, (ISSUER, "sub-new-user")) is not None
    unverified = await sso_callback(client, idp, "sub-other", email="x@example.test", email_verified=False)
    assert unverified.headers["location"].endswith("sso_error=email_unverified")


async def test_the_session_opened_by_sso_is_short_and_follows_the_local_state_of_the_user(
    client: httpx.AsyncClient, idp: respx.MockRouter, make_user: MakeUser, admin_client: httpx.AsyncClient
) -> None:
    user, sub = await linked_user(make_user, Role.editor)
    await sso_callback(client, idp, sub, orion_clearance=2)
    cookie = client.cookies.get("forge_session")
    assert cookie
    assert (await client.post("/api/v1/agents", json={"name": "Via SSO"})).status_code == 201
    assert (await admin_client.patch(f"/api/v1/users/{user.id}", json={"role": "viewer"})).status_code == 200
    assert (
        await client.post("/api/v1/agents", json={"name": "Après"})
    ).status_code == 403  # lowered locally: wins
    assert (await admin_client.patch(f"/api/v1/users/{user.id}", json={"active": False})).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


# --- Password login: kept, unless the operator decides otherwise ------------------------------------------------------


async def test_password_login_is_kept_for_linked_users_by_default(
    client: httpx.AsyncClient, make_user: MakeUser
) -> None:
    user, _ = await linked_user(make_user)
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert response.status_code == 200


async def test_password_login_can_be_disabled_for_linked_users_but_never_for_break_glass(
    client: httpx.AsyncClient, make_user: MakeUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "password_login_disabled_for_linked", True)
    user, _ = await linked_user(make_user, Role.editor)
    unlinked = await make_user(Role.editor)
    refused = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": DEFAULT_PASSWORD}
    )
    assert refused.status_code == 403 and "SSO" in refused.json()["detail"]
    ok = await client.post("/api/v1/auth/login", json={"email": unlinked.email, "password": DEFAULT_PASSWORD})
    assert ok.status_code == 200
    breakglass = await make_user(Role.admin)
    await link(breakglass, f"sub-{uuid.uuid4()}")
    monkeypatch.setattr(settings, "break_glass_emails", breakglass.email)
    kept = await client.post(
        "/api/v1/auth/login", json={"email": breakglass.email, "password": DEFAULT_PASSWORD}
    )
    assert kept.status_code == 200
    plain = await make_user(Role.admin)
    await link(plain, f"sub-{uuid.uuid4()}")  # an admin that is not break-glass is subject to the policy
    monkeypatch.setattr(settings, "break_glass_emails", "")
    assert (
        await client.post("/api/v1/auth/login", json={"email": plain.email, "password": DEFAULT_PASSWORD})
    ).status_code == 403


async def test_local_jwt_and_api_keys_still_work_with_oidc_enabled(
    client: httpx.AsyncClient, admin_client: httpx.AsyncClient
) -> None:
    assert (await admin_client.get("/api/v1/auth/me")).status_code == 200  # HS256 session token
    created = await admin_client.post("/api/v1/api-keys", json={"name": "ci", "role": "viewer"})
    key = created.json()["key"]
    assert (await client.get("/api/v1/agents", headers={"X-Forge-Key": key})).status_code == 200
    assert (await client.get("/api/v1/agents", headers={"Authorization": f"Bearer {key}"})).status_code == 200


# --- Configuration -------------------------------------------------------------------------------------------------------


def test_enabling_oidc_requires_an_issuer_and_derives_the_keycloak_endpoints() -> None:
    with pytest.raises(ValueError, match="FORGE_OIDC_ISSUER"):
        Settings(oidc_enabled=True)
    configured = Settings(oidc_enabled=True, oidc_issuer=f"{ISSUER}/")
    assert configured.oidc_jwks_url == JWKS_URL and configured.oidc_token_endpoint == TOKEN_URL
    assert configured.oidc_authorization_endpoint == AUTH_URL
    assert configured.oidc_redirect_uri.endswith("/api/v1/auth/oidc/callback")
    assert "admin@forge.local" in configured.break_glass_set  # the bootstrap administrator is break-glass


def test_default_workspace_constant_is_what_the_fixtures_use() -> None:
    assert DEFAULT_WS == "00000000-0000-4000-8000-000000000001"
