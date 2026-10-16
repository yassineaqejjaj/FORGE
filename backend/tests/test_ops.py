"""Operations commands: secret rotation keeps every credential readable."""

from __future__ import annotations

import os

from forge.domain.enums import ProviderKind
from forge.infra.db import get_sessionmaker
from forge.infra.models import ProviderCredential
from forge.services.credentials import create_credential, decrypt_credential


async def test_rotate_secrets_reencrypts_with_new_key(app, monkeypatch) -> None:
    from forge.config import settings
    from forge.ops.__main__ import check_secrets, rotate_secrets

    async with get_sessionmaker()() as session:
        credential = await create_credential(
            session, name=f"rot-{os.urandom(3).hex()}", kind=ProviderKind.openai, secret="sk-rotation-test-1234",
            headers={"X-Tenant": "nordalis"},
        )  # fmt: skip
        await session.commit()
        credential_id = credential.id

    old_key = settings.secrets_key
    monkeypatch.setattr(settings, "secrets_key", "forge-new-secrets-key-0123456789abcdef-rotation")
    monkeypatch.setenv("FORGE_SECRETS_KEY_OLD", old_key)
    assert await rotate_secrets() == 0
    assert await check_secrets() == 0
    async with get_sessionmaker()() as session:
        row = await session.get(ProviderCredential, credential_id)
        assert decrypt_credential(row) == {"api_key": "sk-rotation-test-1234", "header:X-Tenant": "nordalis"}
    # Rotation is idempotent (already rotated secrets are kept).
    assert await rotate_secrets() == 0


async def test_workspace_commands(app, monkeypatch, capsys) -> None:
    import uuid

    from sqlalchemy import select

    from forge.config import settings
    from forge.infra.models import EvaluationConfig, Project, Workspace, WorkspaceMember
    from forge.ops.__main__ import project_create, workspace_add_user, workspace_create, workspace_list
    from forge.services.users import create_user

    slug = f"ops-{uuid.uuid4().hex[:6]}"
    monkeypatch.setattr(settings, "workspace_enforcement", "off")
    assert await workspace_create(slug, "Espace d'essai", None, allow_off=False) == 2  # refused while off
    assert await workspace_create(slug, "Espace d'essai", None, allow_off=True) == 0
    assert await workspace_create(slug, "Doublon", None, allow_off=True) == 2
    assert await project_create(slug, "p1", "Projet 1", None) == 0
    assert await project_create(slug, "p1", "Doublon", None) == 2
    async with get_sessionmaker()() as session:
        user = await create_user(
            session, email=f"{slug}@example.com", full_name="Ops", password="Mot-de-passe-123"
        )
        await session.commit()
        workspace = await session.scalar(select(Workspace).where(Workspace.slug == slug))
        assert workspace is not None
        assert await session.scalar(select(Project.id).where(Project.workspace_id == workspace.id))
        config = await session.scalar(
            select(EvaluationConfig).where(EvaluationConfig.key == f"forge-default-{slug}")
        )
        assert config is not None and config.workspace_id == workspace.id  # own default configuration
    assert await workspace_add_user(slug, user.email) == 0
    assert await workspace_add_user(slug, "inconnu@example.com") == 2
    async with get_sessionmaker()() as session:
        member = await session.get(WorkspaceMember, user.id)
        assert member is not None and member.workspace_id == workspace.id
    assert await workspace_list() == 0
    assert slug in capsys.readouterr().out
