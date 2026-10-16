"""FORGE's service account towards NOVA (NOV-112): ``token`` (default) is untouched, ``oidc`` / ``both`` fetch a
client-credentials token (cached, never logged)."""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from forge.adapters.registry import get_adapter
from forge.config import Settings, settings
from forge.domain.enums import AdapterKind
from forge.domain.traces.recorder import InMemoryTraceRecorder
from forge.domain.types import AgentExecutionError
from forge.infra import service_token
from tests.unit.test_adapters import make_request

TOKEN_URL = "https://idp.orion.test/realms/orion/protocol/openid-connect/token"
NOVA = "https://nova.example/v1/agents/pm/runs"
STATIC = "static-nova-inbound-token"
SERVICE_SECRET = "synthetic-client-secret"


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    service_token.clear_cache()
    monkeypatch.setattr(settings, "service_client_secret", SERVICE_SECRET)
    monkeypatch.setattr(settings, "service_token_endpoint", TOKEN_URL)


def _call():
    request = make_request(
        AdapterKind.nova,
        adapter_config={"nova_agent_id": "pm"},
        credentials={"base_url": "https://nova.example", "api_key": STATIC},
    )
    return get_adapter("nova").invoke(request, InMemoryTraceRecorder())


def _nova(router: respx.MockRouter) -> respx.Route:
    return router.post(NOVA).mock(return_value=httpx.Response(200, json={"output": "ok"}))


def test_the_default_is_the_static_token() -> None:
    assert Settings.model_fields["nova_service_auth"].default == "token"
    assert Settings.model_fields["api_key_require_explicit"].default is False
    assert Settings.model_fields["api_key_max_days"].default == 0


async def test_token_mode_sends_the_static_token_and_never_calls_the_idp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "nova_service_auth", "token")
    with respx.mock(assert_all_called=False) as router:
        nova, idp = _nova(router), router.post(TOKEN_URL).mock(return_value=httpx.Response(500))
        await _call()
    assert nova.calls.last.request.headers["authorization"] == f"Bearer {STATIC}" and idp.call_count == 0


async def test_oidc_mode_sends_a_cached_client_credentials_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "nova_service_auth", "oidc")
    with respx.mock(assert_all_called=False) as router:
        nova = _nova(router)
        idp = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "idp-service-token", "expires_in": 300})
        )
        await _call()
        await _call()
    assert nova.calls.last.request.headers["authorization"] == "Bearer idp-service-token"
    assert idp.call_count == 1  # cached until shortly before it expires
    form = idp.calls.last.request.content.decode()
    assert "grant_type=client_credentials" in form and "scope=orion-audience-nova+orion%3Arun.execute" in form


async def test_an_expiring_token_is_renewed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "nova_service_auth", "oidc")
    with respx.mock(assert_all_called=False) as router:
        _nova(router)
        idp = router.post(TOKEN_URL).mock(
            return_value=httpx.Response(200, json={"access_token": "short", "expires_in": 10})
        )
        await _call()
        await _call()
    assert idp.call_count == 2  # 10 s is inside the safety margin: never reused


async def test_oidc_mode_fails_closed_but_both_falls_back_to_the_static_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with respx.mock(assert_all_called=False) as router:
        nova = _nova(router)
        router.post(TOKEN_URL).mock(return_value=httpx.Response(503))
        monkeypatch.setattr(settings, "nova_service_auth", "oidc")
        with pytest.raises(AgentExecutionError) as refused:
            await _call()
        assert refused.value.retryable and nova.call_count == 0  # no silent downgrade in oidc mode
        monkeypatch.setattr(settings, "nova_service_auth", "both")
        with caplog.at_level(logging.WARNING, logger="forge.service_token"):
            await _call()
    assert nova.calls.last.request.headers["authorization"] == f"Bearer {STATIC}"
    assert SERVICE_SECRET not in caplog.text and "idp-service-token" not in caplog.text


def test_oidc_modes_need_a_secret_and_an_endpoint() -> None:
    with pytest.raises(ValueError, match="FORGE_SERVICE_CLIENT_SECRET"):
        Settings(nova_service_auth="oidc")
    with pytest.raises(ValueError, match="FORGE_SERVICE_TOKEN_ENDPOINT"):
        Settings(nova_service_auth="both", service_client_secret="x")
    derived = Settings(
        nova_service_auth="both", service_client_secret="x", oidc_issuer="https://idp.orion.test/realms/orion"
    )
    assert derived.service_token_endpoint == TOKEN_URL
