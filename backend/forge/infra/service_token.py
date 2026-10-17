"""FORGE's own service account (client credentials) towards NOVA (ADR 001 §7, NOV-112).

``FORGE_NOVA_SERVICE_AUTH=token`` (default) never reaches this module. With ``oidc`` or ``both`` FORGE
asks the realm for a short-lived token (``scope`` = NOVA's audience + ``orion:run.execute``), caches it
until shortly before it expires, and sends it as the Bearer of its calls to NOVA. The secret and the token
are never logged.
"""

from __future__ import annotations

import logging
import time

import httpx

from forge.config import settings

logger = logging.getLogger("forge.service_token")

EXPIRY_MARGIN_SECONDS = 30.0
HTTP_TIMEOUT_SECONDS = 5.0
_cache: dict[str, tuple[str, float]] = {}


def clear_cache() -> None:
    _cache.clear()


class ServiceTokenError(Exception):
    """The realm refused or could not be reached; the message carries no secret."""


async def service_token() -> str:
    """A valid service token for NOVA (cached), or :class:`ServiceTokenError`."""
    now = time.monotonic()
    cached = _cache.get("nova")
    if cached is not None and cached[1] - EXPIRY_MARGIN_SECONDS > now:
        return cached[0]
    form = {
        "grant_type": "client_credentials",
        "client_id": settings.service_client_id,
        "client_secret": settings.service_client_secret,
        "scope": settings.nova_service_scope,
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = await client.post(settings.service_token_endpoint, data=form)
    except httpx.HTTPError as exc:
        raise ServiceTokenError(f"fournisseur d'identité injoignable ({type(exc).__name__})") from exc
    if response.status_code != 200:
        raise ServiceTokenError(f"jeton de service refusé (HTTP {response.status_code})")
    try:
        body = response.json()
        access = str(body["access_token"])
        lifetime = float(body.get("expires_in", 60))
    except (ValueError, KeyError, TypeError) as exc:
        raise ServiceTokenError("réponse du fournisseur d'identité invalide") from exc
    _cache["nova"] = (access, now + max(lifetime, 0.0))
    return access


async def nova_bearer(static_token: str | None) -> str | None:
    """The Bearer sent to NOVA under ``FORGE_NOVA_SERVICE_AUTH`` (``static_token``: the credential's)."""
    mode = settings.nova_service_auth
    if mode == "token":
        return static_token
    try:
        return await service_token()
    except ServiceTokenError as exc:
        if mode == "both" and static_token:
            logger.warning("service token unavailable (%s): falling back to the static token", exc)
            return static_token
        raise
