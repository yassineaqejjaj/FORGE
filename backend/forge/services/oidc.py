"""OIDC relying party (ADR 001 §2, §4, §8; ticket NOV-108; docs/OIDC.md). Disabled by default.

* **Validation** of IdP tokens is the verified copy of NOVA's claims contract (``forge.domain.orion_claims``):
  RS256 only, signature against the realm JWKS (cached, refreshed once when a ``kid`` is unknown), ``iss``,
  ``aud`` = ``forge``, ``exp``, ``nbf``; malformed contract claims reject the token.
* **Mapping** (ADR §4): role = local role capped by the highest ``forge-*`` realm role (never raised),
  clearance = ``min(local, orion_clearance)``, workspace = ``orion_workspace_id`` (must be the user's own).
  The token proves who the user is; it never grants a right on its own.
* **Account link**: an IdP identity is tied to a local user only after the user confirms it (verified e-mail,
  explicit confirmation *and* the local password), never automatically. No account is created unless
  ``FORGE_OIDC_AUTO_PROVISION`` is set.
* The browser flow is Authorization Code + PKCE (S256) driven by the API (BFF): the IdP token is validated
  and dropped; FORGE opens its own ``forge_session`` cookie, carrying the caps derived from the token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.config import settings
from forge.domain import orion_claims
from forge.domain.enums import Role
from forge.infra.models import ExternalIdentity, User
from forge.services import audit
from forge.services import users as user_service
from forge.services import workspaces as workspace_service
from forge.services.audit import Actor

logger = logging.getLogger("forge.oidc")

SERVICE = "forge"
STATE_TTL_SECONDS = 600
LINK_TTL_SECONDS = 600
HTTP_TIMEOUT_SECONDS = 5.0


class OidcAuthError(Exception):
    """The SSO request is refused: ``status`` is the HTTP status, ``code`` a stable reason."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


# --- JWKS (cached, rotation-aware) ----------------------------------------------------------------


class JwksCache:
    def __init__(self) -> None:
        self.jwks: dict[str, Any] | None = None
        self.fetched_at = 0.0

    def clear(self) -> None:
        self.jwks, self.fetched_at = None, 0.0

    async def get(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        fresh = self.jwks is not None and now - self.fetched_at < settings.oidc_jwks_cache_seconds
        if fresh and not force:
            assert self.jwks is not None
            return self.jwks
        if force and self.jwks is not None and now - self.fetched_at < settings.oidc_jwks_min_refresh_seconds:
            return self.jwks  # an unknown kid cannot make FORGE hammer the IdP
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.get(settings.oidc_jwks_url)
                response.raise_for_status()
                keys = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            if self.jwks is not None:  # IdP unavailable: keep serving with the last known keys
                logger.warning("JWKS refresh failed (%s): using the cached keys", type(exc).__name__)
                return self.jwks
            raise OidcAuthError(503, "idp_unavailable", "Fournisseur d'identité indisponible") from exc
        if not isinstance(keys, dict) or not isinstance(keys.get("keys"), list):
            raise OidcAuthError(503, "idp_unavailable", "Réponse JWKS invalide")
        self.jwks, self.fetched_at = keys, now
        return keys


jwks_cache = JwksCache()


def is_idp_token(token: str) -> bool:
    """A Bearer JWT signed with RS256 is an IdP token; FORGE's own session tokens are HS256."""
    try:
        return jwt.get_unverified_header(token).get("alg") == "RS256"
    except jwt.PyJWTError:
        return False


async def validate(token: str, *, audience: str | None = None) -> orion_claims.Claims:
    """Verify an IdP token (contract module) or raise :class:`OidcAuthError`."""
    audience = audience or settings.oidc_audience
    for attempt in (0, 1):
        jwks = await jwks_cache.get(force=attempt == 1)
        try:
            return orion_claims.validate_token(
                token,
                jwks,
                issuer=settings.oidc_issuer,
                audience=audience,
                leeway=settings.oidc_clock_leeway_seconds,
            )
        except orion_claims.ClaimsError as exc:
            if exc.code == "unknown_key" and attempt == 0:
                continue  # the realm may have rotated its keys: refresh once, then decide
            raise OidcAuthError(401, exc.code, "Jeton SSO refusé") from exc
    raise AssertionError("unreachable")  # pragma: no cover


# --- What a token grants (ADR §4) -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OidcContext:
    """Caps derived from a validated token. Stored in the FORGE session so they can be re-applied to the
    *current* local state of the user on every request (a lowered local role or clearance wins at once)."""

    issuer: str
    subject: str
    workspace_id: str
    role_cap: str | None  # highest forge-* realm role, ``None``: no cap
    clearance: int | None  # ``orion_clearance`` claim, ``None``: absent
    mfa: bool
    delegated_by: str | None = None

    def to_claim(self) -> dict[str, Any]:
        return {
            "iss": self.issuer,
            "sub": self.subject,
            "ws": self.workspace_id,
            "rr": self.role_cap,
            "clr": self.clearance,
            "mfa": self.mfa,
            "act": self.delegated_by,
        }

    @classmethod
    def from_claim(cls, data: dict[str, Any]) -> OidcContext:
        return cls(
            issuer=str(data["iss"]),
            subject=str(data["sub"]),
            workspace_id=str(data["ws"]),
            role_cap=data.get("rr"),
            clearance=data.get("clr"),
            mfa=bool(data.get("mfa")),
            delegated_by=data.get("act"),
        )


def context_of(claims: orion_claims.Claims) -> OidcContext:
    if claims.is_service:
        raise OidcAuthError(
            403,
            "service_account",
            "Les comptes de service utilisent une clé d'API fgk_… (pas d'identité SSO)",
        )
    if not claims.workspace_id:
        raise OidcAuthError(
            403, "no_workspace", "Jeton sans espace (orion_workspace_id) : aucune ressource ouverte"
        )
    held = [r for r in orion_claims.FORGE_ROLES if r in claims.roles_for(SERVICE)]
    return OidcContext(
        issuer=claims.issuer,
        subject=claims.subject,
        workspace_id=claims.workspace_id,
        role_cap=held[-1] if held else None,
        clearance=claims.clearance,
        mfa=claims.mfa,
        delegated_by=claims.actor.subject if claims.actor else None,
    )


def apply(user: User, ctx: OidcContext) -> tuple[Role, int]:
    """Effective ``(role, clearance)``: the local values, capped by the token (never raised)."""
    role = orion_claims.cap_role(Role(user.role).value, ctx.role_cap, orion_claims.FORGE_ROLES)
    assert role is not None
    return Role(role), orion_claims.effective_clearance(int(user.clearance), ctx.clearance)


async def find_link(session: AsyncSession, issuer: str, subject: str) -> ExternalIdentity | None:
    return await session.get(ExternalIdentity, (issuer, subject))


async def is_linked(session: AsyncSession, user_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(ExternalIdentity.sub).where(ExternalIdentity.user_id == user_id).limit(1)
    )
    return found is not None


async def authenticate_bearer(session: AsyncSession, token: str) -> tuple[User, OidcContext]:
    """A Bearer IdP token -> the linked, active local user and what the token caps."""
    claims = await validate(token)
    ctx = context_of(claims)
    link = await find_link(session, claims.issuer, claims.subject)
    if link is None:
        raise OidcAuthError(401, "unlinked", "Identité SSO non liée à un compte FORGE")
    user = await session.get(User, link.user_id)
    if user is None or not user.active:
        raise OidcAuthError(401, "inactive", "Compte désactivé ou introuvable")
    await check_workspace(session, user, ctx)
    return user, ctx


async def check_workspace(session: AsyncSession, user: User, ctx: OidcContext) -> None:
    """The token's workspace must be the user's own (membership): a token never moves a user across spaces."""
    own = await workspace_service.workspace_id_of_user(session, user.id)
    if str(own) != ctx.workspace_id:
        raise OidcAuthError(403, "workspace_mismatch", "L'espace du jeton n'est pas celui de ce compte")


# --- Browser flow: Authorization Code + PKCE ------------------------------------------------------


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def safe_next(value: str | None) -> str:
    """Post-login target: a path of this application only (never an absolute URL: no open redirect)."""
    if (
        value
        and value.startswith("/")
        and not value.startswith("//")
        and "\\" not in value
        and "\n" not in value
    ):
        return value
    return "/"


def _sign(typ: str, payload: dict[str, Any], ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    claims = {
        **payload,
        "typ": typ,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def _read(typ: str, token: str | None) -> dict[str, Any]:
    if not token:
        raise OidcAuthError(400, "missing_state", "Session de connexion SSO absente ou expirée")
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "iat"]}
        )
    except jwt.PyJWTError as exc:
        raise OidcAuthError(400, "invalid_state", "Session de connexion SSO invalide ou expirée") from exc
    if payload.get("typ") != typ:
        raise OidcAuthError(400, "invalid_state", "Session de connexion SSO invalide")
    return payload


def read_state(cookie: str | None) -> dict[str, Any]:
    """The signed login-attempt cookie (``state``, ``nonce``, PKCE verifier, ``next``)."""
    return _read("oidc_state", cookie)


def authorization_request(next_path: str | None) -> tuple[str, str]:
    """``(IdP authorization URL, signed state cookie value)`` for one login attempt."""
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(64)
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.oidc_redirect_uri,
            "scope": settings.oidc_scopes,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    cookie = _sign(
        "oidc_state",
        {"state": state, "nonce": nonce, "cv": verifier, "next": safe_next(next_path)},
        STATE_TTL_SECONDS,
    )
    return f"{settings.oidc_authorization_endpoint}?{query}", cookie


async def exchange_code(code: str, verifier: str) -> dict[str, Any]:
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.oidc_redirect_uri,
        "client_id": settings.oidc_client_id,
        "code_verifier": verifier,
    }
    if settings.oidc_client_secret:
        form["client_secret"] = settings.oidc_client_secret
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.oidc_token_endpoint, data=form)
    except httpx.HTTPError as exc:
        raise OidcAuthError(503, "idp_unavailable", "Fournisseur d'identité indisponible") from exc
    if response.status_code != 200:
        raise OidcAuthError(401, "code_refused", "Code d'autorisation refusé par le fournisseur d'identité")
    try:
        body = response.json()
    except ValueError as exc:
        raise OidcAuthError(502, "bad_token_response", "Réponse du fournisseur d'identité invalide") from exc
    if not isinstance(body, dict) or not isinstance(body.get("access_token"), str):
        raise OidcAuthError(502, "bad_token_response", "Réponse du fournisseur d'identité invalide")
    return body


def _id_token_nonce(id_token: str) -> str | None:
    """Nonce of an id_token **already validated** (signature, issuer, audience) by :func:`validate`."""
    body = id_token.split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    nonce = payload.get("nonce")
    return nonce if isinstance(nonce, str) else None


async def verify_tokens(token_response: dict[str, Any], expected_nonce: str) -> orion_claims.Claims:
    """Validate the access token (audience ``forge``) and the id_token (client id audience, nonce)."""
    claims = await validate(token_response["access_token"])
    id_token = token_response.get("id_token")
    if isinstance(id_token, str):
        id_claims = await validate(id_token, audience=settings.oidc_client_id)
        if id_claims.subject != claims.subject or _id_token_nonce(id_token) != expected_nonce:
            raise OidcAuthError(401, "invalid_nonce", "Jeton d'identité incohérent (nonce ou sujet)")
    return claims


# --- Linking and provisioning ---------------------------------------------------------------------


def create_link_token(claims: orion_claims.Claims, ctx: OidcContext, user_id: uuid.UUID) -> str:
    return _sign(
        "oidc_link",
        {"ctx": ctx.to_claim(), "email": claims.email, "name": claims.name, "uid": str(user_id)},
        LINK_TTL_SECONDS,
    )


def read_link_token(token: str | None) -> tuple[OidcContext, uuid.UUID, str | None, str | None]:
    payload = _read("oidc_link", token)
    return (
        OidcContext.from_claim(payload["ctx"]),
        uuid.UUID(payload["uid"]),
        payload.get("email"),
        payload.get("name"),
    )


async def candidate_for_link(session: AsyncSession, claims: orion_claims.Claims) -> User | None:
    """The local account an identity may ask to link: same **verified** e-mail, active, not already linked."""
    if not claims.email_matchable or claims.email is None:
        return None
    user = await user_service.get_by_email(session, claims.email)
    if user is None or not user.active:
        return None
    return user


async def link_identity(session: AsyncSession, user: User, ctx: OidcContext) -> ExternalIdentity:
    """Tie ``ctx``'s IdP identity to ``user`` (flush; caller commits). One identity per (issuer, user)."""
    if await find_link(session, ctx.issuer, ctx.subject) is not None:
        raise OidcAuthError(409, "already_linked", "Cette identité SSO est déjà liée à un compte")
    other = await session.scalar(
        select(ExternalIdentity.sub).where(
            ExternalIdentity.issuer == ctx.issuer, ExternalIdentity.user_id == user.id
        )
    )
    if other is not None:
        raise OidcAuthError(409, "user_already_linked", "Ce compte est déjà lié à une autre identité SSO")
    link = ExternalIdentity(issuer=ctx.issuer, sub=ctx.subject, user_id=user.id)
    session.add(link)
    await session.flush()
    await audit.record(
        session,
        Actor.from_user(user),
        "auth.oidc_link",
        "user",
        user.id,
        summary=f"Liaison SSO confirmée par {user.full_name}",
        details={"issuer": ctx.issuer, "sub": ctx.subject},
    )
    return link


async def provision_user(session: AsyncSession, claims: orion_claims.Claims, ctx: OidcContext) -> User:
    """``FORGE_OIDC_AUTO_PROVISION``: create the account of a verified identity (lowest rights)."""
    if not claims.email_matchable or claims.email is None:
        raise OidcAuthError(
            403, "email_unverified", "Adresse e-mail non vérifiée par le fournisseur d'identité"
        )
    workspace = await workspace_service.get_workspace(session, ctx.workspace_id)
    user = await user_service.create_user(
        session,
        email=claims.email,
        full_name=claims.name or claims.email,
        password=secrets.token_urlsafe(48),  # unusable: this account signs in through the IdP
        role=Role.viewer,
        clearance=min(1, ctx.clearance) if ctx.clearance is not None else 1,
        workspace_id=workspace.id,
    )
    await audit.record(
        session,
        Actor.from_user(user),
        "auth.oidc_provision",
        "user",
        user.id,
        summary=f"Compte créé par SSO pour {user.email}",
        details={"issuer": ctx.issuer, "sub": ctx.subject, "workspace_id": ctx.workspace_id},
    )
    return user


def open_session_token(user: User, ctx: OidcContext) -> str:
    """The FORGE session opened by SSO: the usual ``forge_session`` JWT plus the caps of the token."""
    from forge.infra.security import create_access_token

    return create_access_token(
        user.id,
        password_hash=user.password_hash,
        ttl_minutes=min(settings.jwt_ttl_minutes, settings.oidc_session_ttl_minutes),
        extra_claims={"oidc": ctx.to_claim()},
    )
