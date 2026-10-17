"""Router ``oidc``: SSO login (Authorization Code + PKCE, BFF) and the explicit account link (NOV-108).

Mounted **only** when ``FORGE_OIDC_ENABLED=true`` (``forge.api.routers.OPTIONAL_ROUTER_MODULES``): with the
default setting these routes do not exist. Bearer IdP tokens are handled by ``forge.api.deps``.

* ``GET  /auth/oidc/login``    → 302 to the IdP (PKCE S256, ``state``, ``nonce``; signed short-lived cookie);
* ``GET  /auth/oidc/callback`` → code exchange, token validation, then: linked user → ``forge_session``;
  verified e-mail of an existing account → pending link (nothing is linked yet); unknown account →
  refused unless ``FORGE_OIDC_AUTO_PROVISION``; errors redirect to ``/login?sso_error=<code>``;
* ``GET  /auth/oidc/link``     → what the user is asked to confirm;
* ``POST /auth/oidc/link``     → the link, only with ``confirm: true`` and the local password.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from forge.api.deps import SessionDep
from forge.api.errors import ApiError, unauthorized
from forge.api.routers.auth import client_ip, set_session_cookie
from forge.api.schemas.auth import OidcLinkIn, OidcLinkPendingOut
from forge.api.schemas.users import UserOut
from forge.config import settings
from forge.infra import cache
from forge.infra.db import utcnow
from forge.infra.models import User
from forge.infra.security import verify_password
from forge.infra.workspace_scope import bind_session
from forge.services import audit
from forge.services import oidc as service
from forge.services.audit import Actor
from forge.services.workspaces import workspace_id_of_user

logger = logging.getLogger("forge.oidc")

router = APIRouter(prefix="/auth/oidc", tags=["auth"])

STATE_COOKIE = "forge_oidc"
LINK_COOKIE = "forge_oidc_link"
LOGIN_PAGE = "/login"
LINK_PAGE = "/oidc/link"


def _cookie(response: Response, name: str, value: str, max_age: int) -> None:
    response.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth/oidc",
    )


def _clear(response: Response, name: str) -> None:
    response.delete_cookie(
        key=name, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/api/v1/auth/oidc"
    )


def _failure(code: str) -> RedirectResponse:
    response = RedirectResponse(f"{LOGIN_PAGE}?sso_error={quote(code)}", status_code=302)
    _clear(response, STATE_COOKIE)
    return response


@router.get("/login", status_code=302, summary="Connexion SSO (redirection vers le fournisseur d'identité)")
async def oidc_login(next: str | None = None) -> RedirectResponse:
    url, cookie = service.authorization_request(next)
    response = RedirectResponse(url, status_code=302)
    _cookie(response, STATE_COOKIE, cookie, service.STATE_TTL_SECONDS)
    return response


async def _open_session(
    session: SessionDep, user: User, ctx: service.OidcContext, next_path: str
) -> Response:
    user.last_login_at = utcnow()
    await audit.record(
        session,
        user,
        "auth.oidc_login",
        "user",
        user.id,
        summary=f"Connexion SSO de {user.full_name}",
        details={"issuer": ctx.issuer, "sub": ctx.subject, "delegated_by": ctx.delegated_by},
    )
    await session.commit()
    response = RedirectResponse(next_path, status_code=302)
    set_session_cookie(response, service.open_session_token(user, ctx), persistent=False)
    _clear(response, STATE_COOKIE)
    return response


@router.get("/callback", status_code=302, summary="Retour du fournisseur d'identité (échange du code)")
async def oidc_callback(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> Response:
    try:
        payload = service.read_state(request.cookies.get(STATE_COOKIE))
        if error:
            raise service.OidcAuthError(401, "idp_" + error[:40], "Refus du fournisseur d'identité")
        if not code or not state or not secrets.compare_digest(state, str(payload["state"])):
            raise service.OidcAuthError(400, "state_mismatch", "Paramètre state invalide")
        if not await cache.hit(f"oidc-state:{state}", 1, window_seconds=service.STATE_TTL_SECONDS):
            raise service.OidcAuthError(400, "state_replayed", "Tentative de connexion déjà utilisée")
        tokens = await service.exchange_code(code, str(payload["cv"]))
        claims = await service.verify_tokens(tokens, str(payload["nonce"]))
        ctx = service.context_of(claims)
        next_path = service.safe_next(payload.get("next"))

        link = await service.find_link(session, ctx.issuer, ctx.subject)
        if link is not None:
            user = await session.get(User, link.user_id)
            if user is None or not user.active:
                raise service.OidcAuthError(403, "inactive", "Compte désactivé ou introuvable")
            bind_session(session, await workspace_id_of_user(session, user.id))
            await service.check_workspace(session, user, ctx)
            return await _open_session(session, user, ctx, next_path)

        candidate = await service.candidate_for_link(session, claims)
        if candidate is not None:
            bind_session(session, await workspace_id_of_user(session, candidate.id))
            await service.check_workspace(session, candidate, ctx)
            response = RedirectResponse(LINK_PAGE, status_code=302)
            _cookie(
                response,
                LINK_COOKIE,
                service.create_link_token(claims, ctx, candidate.id),
                service.LINK_TTL_SECONDS,
            )
            _clear(response, STATE_COOKIE)
            return response  # nothing is linked until the user confirms
        if settings.oidc_auto_provision:
            user = await service.provision_user(session, claims, ctx)
            await service.link_identity(session, user, ctx)
            bind_session(session, await workspace_id_of_user(session, user.id))
            return await _open_session(session, user, ctx, next_path)
        raise service.OidcAuthError(403, "unknown_account", "Aucun compte FORGE pour cette identité")
    except service.OidcAuthError as exc:
        await session.rollback()
        logger.info("SSO login refused: %s (ip %s)", exc.code, client_ip(request))
        return _failure(exc.code)


def _pending(request: Request) -> tuple[service.OidcContext, str, str | None, str | None]:
    try:
        ctx, user_id, email, name = service.read_link_token(request.cookies.get(LINK_COOKIE))
    except service.OidcAuthError as exc:
        raise unauthorized("Aucune liaison SSO en attente (ou expirée) : reconnectez-vous par SSO") from exc
    return ctx, str(user_id), email, name


@router.get("/link", response_model=OidcLinkPendingOut, summary="Liaison SSO en attente de confirmation")
async def oidc_link_pending(request: Request, session: SessionDep) -> OidcLinkPendingOut:
    ctx, user_id, email, name = _pending(request)
    user = await session.get(User, uuid.UUID(user_id))
    if user is None or not user.active:
        raise unauthorized("Compte introuvable ou désactivé")
    return OidcLinkPendingOut(
        account_email=user.email,
        account_name=user.full_name,
        idp_email=email,
        idp_name=name,
        issuer=ctx.issuer,
    )


@router.post(
    "/link", response_model=UserOut, summary="Lier mon compte FORGE à l'identité SSO (confirmation explicite)"
)
async def oidc_link_confirm(
    body: OidcLinkIn, request: Request, response: Response, session: SessionDep
) -> UserOut:
    ctx, user_id, _email, _name = _pending(request)
    user = await session.get(User, uuid.UUID(user_id))
    if user is None or not user.active:
        raise unauthorized("Compte introuvable ou désactivé")
    bind_session(session, await workspace_id_of_user(session, user.id))
    if not body.confirm:
        raise ApiError(
            400, "Confirmation explicite requise pour lier le compte", code="confirmation_required"
        )
    if not await cache.hit(f"oidc-link:{user.id}", settings.login_rate_limit_per_minute, window_seconds=60):
        raise ApiError(429, "Trop de tentatives : réessayez dans une minute", code="rate_limited")
    if not verify_password(body.password, user.password_hash):
        await audit.record(
            session,
            Actor.system(),
            "auth.oidc_link_refused",
            "user",
            user.id,
            summary=f"Liaison SSO refusée pour {user.email} (mot de passe incorrect)",
            details={"issuer": ctx.issuer, "ip": client_ip(request)},
        )
        await session.commit()
        raise unauthorized("Mot de passe incorrect")
    try:
        await service.check_workspace(session, user, ctx)
        await service.link_identity(session, user, ctx)
    except service.OidcAuthError as exc:
        await session.rollback()
        raise ApiError(exc.status, exc.detail, code=exc.code) from exc
    await audit.record(
        session, user, "auth.oidc_login", "user", user.id, summary=f"Connexion SSO de {user.full_name}",
        details={"issuer": ctx.issuer, "sub": ctx.subject},
    )  # fmt: skip
    user.last_login_at = utcnow()
    await session.commit()
    set_session_cookie(response, service.open_session_token(user, ctx), persistent=False)
    _clear(response, LINK_COOKIE)
    return UserOut.model_validate(user)
