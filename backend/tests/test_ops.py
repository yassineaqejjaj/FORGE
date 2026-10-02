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
