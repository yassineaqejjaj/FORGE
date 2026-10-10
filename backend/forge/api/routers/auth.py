"""Router ``auth``: login (httpOnly session cookie), logout, current user, password change (§3.1)."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Request, Response, status

from forge.api.deps import CurrentUser, SessionDep, session_token
from forge.api.errors import ApiError, bad_request, forbidden, unauthorized
from forge.api.schemas.auth import LoginIn, LoginOut, PasswordChangeIn
from forge.api.schemas.users import UserOut
from forge.config import settings
from forge.infra import cache
from forge.infra.db import utcnow
from forge.infra.models import User
from forge.infra.security import (
    SESSION_COOKIE_NAME,
    TokenError,
    create_access_token,
    decode_access_token,
    hash_password,
    password_needs_rehash,
    verify_password,
)
from forge.services import audit
from forge.services.audit import Actor
from forge.services.users import get_by_email, normalize_email

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_CREDENTIALS = "E-mail ou mot de passe incorrect"
RATE_LIMITED = "Trop de tentatives de connexion : réessayez dans une minute"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def set_session_cookie(response: Response, token: str, *, persistent: bool = True) -> None:
    """``persistent=False``: browser-session cookie (« Rester connecté » unchecked); same token TTL."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.session_ttl_seconds if persistent else None,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE_NAME, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )


@router.post("/login", response_model=LoginOut, summary="Connexion (cookie de session httpOnly)")
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> LoginOut:
    email = normalize_email(body.email)
    ip = client_ip(request)
    if not await cache.hit(f"login:{email}:{ip}", settings.login_rate_limit_per_minute, window_seconds=60):
        raise ApiError(429, RATE_LIMITED, code="rate_limited", headers={"Retry-After": "60"})
    user = await get_by_email(session, email)
    password_ok = verify_password(body.password, user.password_hash if user else None)
    if user is None or not password_ok or not user.active:
        await audit.record(
            session,
            Actor.system(),
            "auth.login_failed",
            "user",
            user.id if user else None,
            summary=f"Échec de connexion pour {email}",
            details={
                "email": email,
                "ip": ip,
                "reason": "inactive" if user and password_ok else "credentials",
            },
        )
        await session.commit()
        if user is not None and password_ok and not user.active:
            raise forbidden("Compte désactivé : contactez un administrateur")
        raise unauthorized(INVALID_CREDENTIALS)
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    await audit.record(
        session,
        user,
        "auth.login",
        "user",
        user.id,
        summary=f"Connexion de {user.full_name}",
        details={"ip": ip},
    )
    await session.commit()
    token = create_access_token(user.id, password_hash=user.password_hash)
    set_session_cookie(response, token, persistent=body.remember)
    return LoginOut(user=UserOut.model_validate(user), token=token if body.return_token else None)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Déconnexion")
async def logout(request: Request, session: SessionDep) -> Response:
    token = session_token(request)
    if token:
        with contextlib.suppress(TokenError):
            claims = decode_access_token(token)
            user = await session.get(User, claims.user_id)
            if user is not None:
                await audit.record(
                    session, user, "auth.logout", "user", user.id, summary=f"Déconnexion de {user.full_name}"
                )
                await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=UserOut, summary="Utilisateur connecté")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/onboarding/complete", response_model=UserOut, summary="Terminer la visite de bienvenue")
async def complete_onboarding(user: CurrentUser, session: SessionDep) -> UserOut:
    """Idempotent: the first call stamps ``onboarded_at`` (finished or skipped), later calls are no-ops."""
    if user.onboarded_at is None:
        user.onboarded_at = utcnow()
        await audit.record(
            session,
            user,
            "auth.onboarding_completed",
            "user",
            user.id,
            summary=f"Visite de bienvenue terminée par {user.full_name}",
        )
        await session.commit()
    return UserOut.model_validate(user)


@router.post(
    "/password", response_model=LoginOut, summary="Changer son mot de passe (révoque les autres sessions)"
)
async def change_password(
    body: PasswordChangeIn, request: Request, response: Response, user: CurrentUser, session: SessionDep
) -> LoginOut:
    if not await cache.hit(f"password:{user.id}", settings.login_rate_limit_per_minute, window_seconds=60):
        raise ApiError(429, RATE_LIMITED, code="rate_limited", headers={"Retry-After": "60"})
    if not verify_password(body.current_password, user.password_hash):
        raise bad_request("Mot de passe actuel incorrect")
    if body.new_password == body.current_password:
        raise bad_request("Le nouveau mot de passe doit être différent de l'actuel")
    user.password_hash = hash_password(body.new_password)
    await audit.record(
        session,
        user,
        "auth.password_change",
        "user",
        user.id,
        summary=f"Changement de mot de passe de {user.full_name}",
        details={"ip": client_ip(request)},
    )
    await session.commit()
    # The password fingerprint in every previous JWT no longer matches: other sessions are revoked.
    token = create_access_token(user.id, password_hash=user.password_hash)
    set_session_cookie(response, token)
    return LoginOut(user=UserOut.model_validate(user), token=token if body.return_token else None)
