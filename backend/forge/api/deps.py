"""FastAPI dependencies: database session, authenticated principal, role checks (docs §3).

Two kinds of callers:

* **users** — session cookie ``forge_session`` or ``Authorization: Bearer <jwt>``;
* **API keys** — ``fgk_…`` via ``Authorization: Bearer fgk_…`` or ``X-Forge-Key`` (CI pipelines,
  NOVA, agents pushing OTLP traces). A key carries a role and a clearance; keys with scopes are
  restricted to those scopes (``traces:write`` keys can only push traces).

Routers declare the minimum role with ``RequireViewer`` … ``RequireAdmin``. Private scenario
content is filtered with :meth:`Principal.can_see_private` (maintainer and above).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Annotated, Literal

from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from forge.api.errors import forbidden, unauthorized
from forge.domain.enums import ActorType, Role, role_at_least
from forge.infra.db import get_session, utcnow
from forge.infra.models import ApiKey, User
from forge.infra.security import (
    API_KEY_HEADER,
    SESSION_COOKIE_NAME,
    TokenError,
    decode_access_token,
    hash_api_key,
    looks_like_api_key,
    parse_api_key,
    password_fingerprint,
    verify_api_key,
)
from forge.services.audit import Actor

SessionDep = Annotated[AsyncSession, Depends(get_session)]

KEY_LAST_USED_RESOLUTION = timedelta(seconds=30)
TRACES_WRITE_SCOPE = "traces:write"


@dataclass(slots=True)
class Principal:
    """Authenticated caller (human user or service API key)."""

    kind: Literal["user", "api_key"]
    id: uuid.UUID
    label: str
    role: Role
    clearance: int
    user: User | None = None
    api_key: ApiKey | None = None
    scopes: list[str] = field(default_factory=list)

    @classmethod
    def for_user(cls, user: User) -> Principal:
        return cls(
            kind="user",
            id=user.id,
            label=user.full_name or user.email,
            role=user.role,
            clearance=int(user.clearance),
            user=user,
        )

    @classmethod
    def for_api_key(cls, key: ApiKey) -> Principal:
        return cls(
            kind="api_key",
            id=key.id,
            label=f"Clé « {key.name} »",
            role=key.role,
            clearance=int(key.clearance),
            api_key=key,
            scopes=list(key.scopes or []),
        )

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.user.id if self.user is not None else None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.admin

    def has_role(self, minimum: Role) -> bool:
        return role_at_least(self.role, minimum)

    def require(self, minimum: Role) -> None:
        if not self.has_role(minimum):
            raise forbidden(_ROLE_MESSAGES[minimum])

    @property
    def can_see_private(self) -> bool:
        """Private scenario content (input, expected output, hidden rules, traces) — maintainers+."""
        return self.has_role(Role.maintainer)

    def can_see_classification(self, level: int) -> bool:
        return int(level) <= self.clearance

    @property
    def actor(self) -> Actor:
        return Actor(ActorType.user if self.kind == "user" else ActorType.api_key, self.id, self.label)


_ROLE_MESSAGES: dict[Role, str] = {
    Role.viewer: "Authentification requise",
    Role.evaluator: "Action réservée aux évaluateurs (rôle evaluator ou supérieur)",
    Role.editor: "Action réservée aux éditeurs (rôle editor ou supérieur)",
    Role.maintainer: "Action réservée aux mainteneurs de benchmarks (rôle maintainer ou supérieur)",
    Role.admin: "Action réservée aux administrateurs de la plateforme",
}


# --- Credential extraction ------------------------------------------------------------------------


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def extract_api_key(request: Request) -> str | None:
    header_key = request.headers.get(API_KEY_HEADER)
    if header_key and header_key.strip():
        return header_key.strip()
    token = _bearer_token(request)
    if token and looks_like_api_key(token):
        return token
    return None


def _session_token(request: Request) -> str | None:
    token = _bearer_token(request)
    if token and not looks_like_api_key(token):
        return token
    return request.cookies.get(SESSION_COOKIE_NAME) or None


async def _user_from_token(session: AsyncSession, token: str) -> User:
    try:
        claims = decode_access_token(token)
    except TokenError as exc:
        raise unauthorized(f"{exc} — veuillez vous reconnecter") from exc
    user = await session.get(User, claims.user_id)
    if user is None or not user.active:
        raise unauthorized("Session invalide — veuillez vous reconnecter")
    if claims.password_fingerprint and claims.password_fingerprint != password_fingerprint(
        user.password_hash
    ):
        raise unauthorized("Session révoquée (mot de passe modifié) — veuillez vous reconnecter")
    return user


async def authenticate_api_key(session: AsyncSession, key: str, *, touch: bool = True) -> ApiKey:
    parsed = parse_api_key(key)
    if parsed is None:
        raise unauthorized("Clé d'API invalide")
    prefix, _secret = parsed
    api_key = await session.scalar(select(ApiKey).where(ApiKey.prefix == prefix))
    if api_key is None:
        verify_api_key(key, hash_api_key("fgk_invalid"))  # equalise timing
        raise unauthorized("Clé d'API invalide")
    if not verify_api_key(key, api_key.key_hash):
        raise unauthorized("Clé d'API invalide")
    now = utcnow()
    if api_key.revoked_at is not None:
        raise unauthorized("Clé d'API révoquée")
    if api_key.expires_at is not None and api_key.expires_at <= now:
        raise unauthorized("Clé d'API expirée")
    if touch and (api_key.last_used_at is None or now - api_key.last_used_at >= KEY_LAST_USED_RESOLUTION):
        await session.execute(update(ApiKey).where(ApiKey.id == api_key.id).values(last_used_at=now))
        api_key.last_used_at = now
        await session.commit()
    return api_key


# --- Dependencies ---------------------------------------------------------------------------------


async def get_principal(request: Request, session: SessionDep) -> Principal:
    """User or API key principal. Scoped keys (``traces:write``) are rejected here."""
    key = extract_api_key(request)
    if key:
        api_key = await authenticate_api_key(session, key)
        if api_key.scopes:
            raise forbidden("Cette clé d'API est limitée à l'envoi de traces")
        return Principal.for_api_key(api_key)
    token = _session_token(request)
    if token is None:
        raise unauthorized("Authentification requise")
    return Principal.for_user(await _user_from_token(session, token))


async def get_trace_writer(request: Request, session: SessionDep) -> Principal:
    """Principal allowed to push traces: any user/key with role editor+, or a ``traces:write`` key."""
    key = extract_api_key(request)
    if key:
        api_key = await authenticate_api_key(session, key)
        principal = Principal.for_api_key(api_key)
        if api_key.scopes and TRACES_WRITE_SCOPE not in api_key.scopes:
            raise forbidden("Cette clé d'API ne permet pas l'envoi de traces")
        if not api_key.scopes:
            principal.require(Role.editor)
        return principal
    token = _session_token(request)
    if token is None:
        raise unauthorized("Authentification requise (clé d'API fgk_… attendue)")
    principal = Principal.for_user(await _user_from_token(session, token))
    principal.require(Role.editor)
    return principal


async def get_current_user(request: Request, session: SessionDep) -> User:
    """Human user only (session cookie or Bearer JWT)."""
    token = _session_token(request)
    if token is None:
        if extract_api_key(request):
            raise forbidden("Cette opération n'est pas accessible avec une clé d'API")
        raise unauthorized("Authentification requise")
    return await _user_from_token(session, token)


def require_role(minimum: Role) -> Callable[..., Awaitable[Principal]]:
    async def _dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        principal.require(minimum)
        return principal

    return _dependency


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
CurrentUser = Annotated[User, Depends(get_current_user)]
TraceWriter = Annotated[Principal, Depends(get_trace_writer)]
RequireViewer = Annotated[Principal, Depends(require_role(Role.viewer))]
RequireEvaluator = Annotated[Principal, Depends(require_role(Role.evaluator))]
RequireEditor = Annotated[Principal, Depends(require_role(Role.editor))]
RequireMaintainer = Annotated[Principal, Depends(require_role(Role.maintainer))]
RequireAdmin = Annotated[Principal, Depends(require_role(Role.admin))]
