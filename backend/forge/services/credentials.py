"""Provider credentials: creation, rotation and resolution of decrypted secrets for adapters/judges.

Secrets are only decrypted in workers at execution time (:func:`resolve_credentials`) and are never
written to manifests, logs or API responses.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import ProviderKind
from forge.infra.db import utcnow
from forge.infra.models import ProviderCredential
from forge.infra.security import decrypt_secret, encrypt_secret, secret_hint


async def create_credential(
    session: AsyncSession,
    *,
    name: str,
    kind: ProviderKind,
    secret: str | None,
    base_url: str | None = None,
    headers: dict[str, str] | None = None,
    description: str = "",
    created_by: uuid.UUID | None = None,
) -> ProviderCredential:
    credential = ProviderCredential(
        name=name.strip(),
        kind=kind,
        base_url=(base_url or "").strip().rstrip("/") or None,
        secret_encrypted=encrypt_secret(secret) if secret else None,
        headers_encrypted=encrypt_secret(json.dumps(headers)) if headers else None,
        secret_hint=secret_hint(secret) if secret else None,
        description=description,
        created_by=created_by,
    )
    session.add(credential)
    await session.flush()
    return credential


async def rotate_credential(
    session: AsyncSession,
    credential: ProviderCredential,
    *,
    secret: str | None = None,
    headers: dict[str, str] | None = None,
    base_url: str | None = None,
) -> ProviderCredential:
    if secret is not None:
        credential.secret_encrypted = encrypt_secret(secret) if secret else None
        credential.secret_hint = secret_hint(secret) if secret else None
    if headers is not None:
        credential.headers_encrypted = encrypt_secret(json.dumps(headers)) if headers else None
    if base_url is not None:
        credential.base_url = base_url.strip().rstrip("/") or None
    credential.rotated_at = utcnow()
    await session.flush()
    return credential


def decrypt_credential(credential: ProviderCredential) -> dict[str, str]:
    """``{"api_key": …, "base_url": …, "header:<Name>": …}`` (only the keys that are set)."""
    resolved: dict[str, str] = {}
    if credential.secret_encrypted:
        resolved["api_key"] = decrypt_secret(credential.secret_encrypted)
    if credential.base_url:
        resolved["base_url"] = credential.base_url
    if credential.headers_encrypted:
        headers = json.loads(decrypt_secret(credential.headers_encrypted))
        for name, value in dict(headers).items():
            resolved[f"header:{name}"] = str(value)
    return resolved


async def resolve_credentials(session: AsyncSession, credential_id: str | uuid.UUID | None) -> dict[str, str]:
    """Decrypted secrets of a credential (empty dict when ``credential_id`` is ``None``/unknown)."""
    if not credential_id:
        return {}
    credential = await session.get(ProviderCredential, uuid.UUID(str(credential_id)))
    if credential is None:
        return {}
    return decrypt_credential(credential)


async def get_by_name(session: AsyncSession, name: str) -> ProviderCredential | None:
    return await session.scalar(select(ProviderCredential).where(ProviderCredential.name == name))
