"""FastAPI dependencies: database session, authenticated principal, role checks (docs §3).

Two kinds of callers:

* **users** — session cookie ``forge_session`` or ``Authorization: Bearer <jwt>``;
* **API keys** — ``fgk_…`` via ``Authorization: Bearer fgk_…`` or ``X-Forge-Key`` (CI pipelines,
  NOVA, agents pushing OTLP traces). A key carries a role and a clearance; keys with scopes are
  restricted to those scopes (``traces:write`` keys can only push traces).

Routers declare the minimum role with ``RequireViewer`` … ``RequireAdmin``. Private scenario
content is filtered with :meth:`Principal.can_see_private` (maintainer and above).

Every authenticated dependency also **binds the database session to the caller's workspace**
(``forge.infra.workspace_scope``): the workspace comes from the validated identity — the user's
membership or the API key's workspace — never from a parameter or a header. Whether the session is
then filtered depends on ``FORGE_WORKSPACE_ENFORCEMENT`` (docs/WORKSPACES.md).
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

from forge.api.errors import ApiError, forbidden, unauthorized
from forge.config import settings
from forge.domain.enums import ActorType, Role, role_at_least
from forge.infra.db import get_session, utcnow
from forge.infra.models import ORION_DEFAULT_WORKSPACE_ID, ApiKey, Project, User
from forge.infra.security import (
    API_KEY_HEADER,
    SESSION_COOKIE_NAME,
    TokenClaims,
    TokenError,
    decode_access_token,
    hash_api_key,
    looks_like_api_key,
    parse_api_key,
    password_fingerprint,
    verify_api_key,
)
from forge.infra.workspace_scope import bind_session
from forge.services import accounts as accounts_service
from forge.services import oidc as oidc_service
from forge.services.audit import Actor
from forge.services.oidc import OidcAuthError, OidcContext
from forge.services.workspaces import workspace_id_of_user

#: Routes whose session is **not** bound to a workspace (no authenticated identity yet, or a platform
#: caller), each with the reason. The inventory test fails for any other route without a binding
#: authentication dependency (``get_principal`` / ``get_trace_writer`` / ``get_current_user``).
UNBOUND_ROUTES: dict[tuple[str, str], str] = {
    (
        "POST",
        "/api/v1/auth/login",
    ): "no identity yet: binds the user's workspace once the password is verified",
    ("POST", "/api/v1/auth/logout"): "binds the workspace of the session token it revokes",
    ("GET", "/api/v1/auth/oidc/login"): "OIDC: redirects an anonymous browser to the IdP",
    ("GET", "/api/v1/auth/oidc/callback"): "OIDC: no identity until the IdP token is validated; binds then",
    ("GET", "/api/v1/auth/oidc/link"): "OIDC: pending link (signed cookie), no session yet",
    ("POST", "/api/v1/auth/oidc/link"): "OIDC: explicit confirmation by password; binds the user's workspace",
    (
        "POST",
        "/api/v1/webhooks/orbit",
    ): "HMAC-signed ORBIT webhook, no user: forgets copies of a document in every workspace",
}
#: Non-API routes (liveness, readiness and Prometheus scrape: aggregated platform counters, no tenant data).
UNBOUND_PLATFORM_PATHS: frozenset[str] = frozenset({"/health", "/ready", "/metrics"})

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
    #: ``orion_workspace_id`` of the caller (isolation boundary) and the project of a project key.
    workspace_id: uuid.UUID = ORION_DEFAULT_WORKSPACE_ID
    project_id: uuid.UUID | None = None
    #: SSO administrator without ``amr`` ∋ ``mfa`` while ``FORGE_REQUIRE_MFA_FOR_ADMIN`` is set.
    needs_mfa: bool = False

    @classmethod
    def for_user(
        cls,
        user: User,
        workspace_id: uuid.UUID = ORION_DEFAULT_WORKSPACE_ID,
        oidc: OidcContext | None = None,
    ) -> Principal:
        role, clearance = user.role, int(user.clearance)
        label = user.full_name or user.email
        needs_mfa = False
        if oidc is not None:  # SSO: the local state capped by the token (ADR §4), never raised
            role, clearance = oidc_service.apply(user, oidc)
            if oidc.delegated_by:
                label = f"{label} (via {oidc.delegated_by})"
            needs_mfa = settings.require_mfa_for_admin and role == Role.admin and not oidc.mfa
        return cls(
            kind="user",
            id=user.id,
            label=label,
            role=role,
            clearance=clearance,
            user=user,
            workspace_id=workspace_id,
            needs_mfa=needs_mfa,
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
            workspace_id=key.workspace_id,
            project_id=key.project_id,
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
        if minimum == Role.admin and self.needs_mfa:
            raise forbidden("Authentification multifacteur requise pour l'administration (amr ∋ mfa)")

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


async def _user_principal(session: AsyncSession, user: User, oidc: OidcContext | None = None) -> Principal:
    workspace_id = await workspace_id_of_user(session, user.id)
    if oidc is not None:
        try:
            await oidc_service.check_workspace(session, user, oidc)
        except OidcAuthError as exc:
            raise ApiError(exc.status, exc.detail, code=exc.code) from exc
    return bind(session, Principal.for_user(user, workspace_id, oidc))


def bind(session: AsyncSession, principal: Principal) -> Principal:
    """Scope the request's session to the caller's workspace (see ``forge.infra.workspace_scope``)."""
    bind_session(session, principal.workspace_id, principal.project_id)
    return principal


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


def session_token(request: Request) -> str | None:
    """Session JWT from the Bearer header (non-API-key) or the ``forge_session`` cookie."""
    token = _bearer_token(request)
    if token and not looks_like_api_key(token):
        return token
    return request.cookies.get(SESSION_COOKIE_NAME) or None


async def _identity_from_token(session: AsyncSession, token: str) -> tuple[User, OidcContext | None]:
    """The user behind a session token or (OIDC enabled) a Bearer IdP token, and what that token caps."""
    if settings.oidc_enabled and oidc_service.is_idp_token(token):
        try:
            return await oidc_service.authenticate_bearer(session, token)
        except OidcAuthError as exc:
            if exc.status == 401:
                raise unauthorized(f"{exc.detail} ({exc.code})") from exc
            raise ApiError(exc.status, exc.detail, code=exc.code) from exc
    user, claims = await _local_user_from_token(session, token)
    oidc = OidcContext.from_claim(claims.oidc) if settings.oidc_enabled and claims.oidc else None
    if oidc is None and await accounts_service.sso_required_without_sso(session, user):
        raise unauthorized("Ce compte exige le SSO : reconnectez-vous par le fournisseur d'identité")
    return user, oidc


async def _local_user_from_token(session: AsyncSession, token: str) -> tuple[User, TokenClaims]:
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
    return user, claims


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
    if api_key.project_id is not None:  # a project key follows its project: out of the workspace = unusable
        project_workspace = await session.scalar(
            select(Project.workspace_id).where(Project.id == api_key.project_id)
        )
        if project_workspace != api_key.workspace_id:
            raise unauthorized("Clé d'API invalide (projet hors de son espace)")
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
        return bind(session, Principal.for_api_key(api_key))
    token = session_token(request)
    if token is None:
        raise unauthorized("Authentification requise")
    user, oidc = await _identity_from_token(session, token)
    return await _user_principal(session, user, oidc)


async def get_trace_writer(request: Request, session: SessionDep) -> Principal:
    """Principal allowed to push traces: any user/key with role editor+, or a ``traces:write`` key."""
    key = extract_api_key(request)
    if key:
        api_key = await authenticate_api_key(session, key)
        principal = bind(session, Principal.for_api_key(api_key))
        if api_key.scopes and TRACES_WRITE_SCOPE not in api_key.scopes:
            raise forbidden("Cette clé d'API ne permet pas l'envoi de traces")
        if not api_key.scopes:
            principal.require(Role.editor)
        return principal
    token = session_token(request)
    if token is None:
        raise unauthorized("Authentification requise (clé d'API fgk_… attendue)")
    user, oidc = await _identity_from_token(session, token)
    principal = await _user_principal(session, user, oidc)
    principal.require(Role.editor)
    return principal


async def get_current_user(request: Request, session: SessionDep) -> User:
    """Human user only (session cookie or Bearer JWT)."""
    token = session_token(request)
    if token is None:
        if extract_api_key(request):
            raise forbidden("Cette opération n'est pas accessible avec une clé d'API")
        raise unauthorized("Authentification requise")
    user, oidc = await _identity_from_token(session, token)
    await _user_principal(session, user, oidc)  # binds the workspace (and checks the token's one)
    return user


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
