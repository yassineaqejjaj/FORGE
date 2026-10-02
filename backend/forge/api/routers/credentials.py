"""Router ``credentials``: encrypted provider credentials (admin, §3.1). Secrets are never returned."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from forge.api.deps import RequireAdmin, RequireMaintainer, SessionDep
from forge.api.errors import conflict, not_found
from forge.api.schemas.credentials import CredentialCreateIn, CredentialOut, CredentialUpdateIn
from forge.infra.models import ProviderCredential
from forge.services import agents as agent_service
from forge.services import audit
from forge.services import credentials as credential_service

router = APIRouter(prefix="/credentials", tags=["credentials"])


def _out(credential: ProviderCredential, usage: tuple[int, int] = (0, 0)) -> CredentialOut:
    return CredentialOut(
        id=credential.id,
        name=credential.name,
        kind=credential.kind,
        base_url=credential.base_url,
        secret_hint=credential.secret_hint,
        has_secret=credential.secret_encrypted is not None,
        has_headers=credential.headers_encrypted is not None,
        description=credential.description,
        created_by=credential.created_by,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
        rotated_at=credential.rotated_at,
        agent_versions_count=usage[0],
        judges_count=usage[1],
    )


async def _get(session: SessionDep, credential_id: uuid.UUID) -> ProviderCredential:
    credential = await session.get(ProviderCredential, credential_id)
    if credential is None:
        raise not_found("Identifiant fournisseur introuvable")
    return credential


@router.get("", response_model=list[CredentialOut], summary="Lister les identifiants fournisseurs")
async def list_credentials(principal: RequireMaintainer, session: SessionDep) -> list[CredentialOut]:
    """Maintainers need the list to pin credentials on judges; secrets are never returned (hint only)."""
    rows = list(await session.scalars(select(ProviderCredential).order_by(ProviderCredential.name)))
    usage = await agent_service.credential_reference_counts(session, [c.id for c in rows])
    return [_out(c, usage.get(c.id, (0, 0))) for c in rows]


@router.post(
    "", response_model=CredentialOut, status_code=status.HTTP_201_CREATED, summary="Créer un identifiant"
)
async def create_credential(
    body: CredentialCreateIn, admin: RequireAdmin, session: SessionDep
) -> CredentialOut:
    if await credential_service.get_by_name(session, body.name):
        raise conflict(f"Un identifiant nommé « {body.name} » existe déjà")
    credential = await credential_service.create_credential(
        session,
        name=body.name,
        kind=body.kind,
        secret=body.secret,
        base_url=body.base_url,
        headers=body.headers,
        description=body.description,
        created_by=admin.user_id,
    )
    await audit.record(
        session,
        admin,
        "credential.create",
        "credential",
        credential.id,
        summary=f"Création de l'identifiant {credential.name} ({credential.kind.value})",
        details={
            "kind": credential.kind,
            "has_secret": bool(body.secret),
            "headers": sorted(body.headers or {}),
        },
    )
    await session.commit()
    return _out(credential)


@router.patch(
    "/{credential_id}", response_model=CredentialOut, summary="Modifier ou faire tourner un identifiant"
)
async def update_credential(
    credential_id: uuid.UUID, body: CredentialUpdateIn, admin: RequireAdmin, session: SessionDep
) -> CredentialOut:
    credential = await _get(session, credential_id)
    changes: dict[str, object] = {}
    if body.name is not None and body.name != credential.name:
        if await credential_service.get_by_name(session, body.name):
            raise conflict(f"Un identifiant nommé « {body.name} » existe déjà")
        changes["name"] = body.name
        credential.name = body.name
    if body.description is not None and body.description != credential.description:
        changes["description"] = body.description
        credential.description = body.description
    if body.secret is not None or body.headers is not None or body.base_url is not None:
        await credential_service.rotate_credential(
            session, credential, secret=body.secret, headers=body.headers, base_url=body.base_url
        )
        changes["rotated"] = [k for k in ("secret", "headers", "base_url") if getattr(body, k) is not None]
    if changes:
        await audit.record(
            session,
            admin,
            "credential.rotate" if "rotated" in changes else "credential.update",
            "credential",
            credential.id,
            summary=f"Modification de l'identifiant {credential.name}",
            details=changes,
        )
        await session.commit()
        await session.refresh(credential)
    usage = await agent_service.credential_references(session, credential.id)
    return _out(credential, usage)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Supprimer un identifiant")
async def delete_credential(credential_id: uuid.UUID, admin: RequireAdmin, session: SessionDep) -> Response:
    credential = await _get(session, credential_id)
    versions, judges = await agent_service.credential_references(session, credential.id)
    if versions or judges:
        raise conflict(
            f"Identifiant utilisé par {versions} version(s) d'agent et {judges} juge(s) : "
            "suppression impossible"
        )
    await session.delete(credential)
    await audit.record(
        session,
        admin,
        "credential.delete",
        "credential",
        credential_id,
        summary=f"Suppression de l'identifiant {credential.name}",
        details={"kind": credential.kind},
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
