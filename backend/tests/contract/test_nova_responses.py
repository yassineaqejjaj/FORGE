"""NOVA -> FORGE (NOV-74): the answers NOVA really gives, read through FORGE's own NOVA adapter.

``tests/fixtures/fap_response`` is a verified copy of NOVA ``contracts/fap_response`` (real route, normalised); each
file is ``{"status_code", "body"}``. No service: NOVA is answered by respx with them.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from forge.adapters.registry import get_adapter
from forge.domain.enums import TraceEventType
from forge.domain.traces.recorder import InMemoryTraceRecorder
from forge.domain.types import AgentExecutionError
from tests.contract.support import FAP_REQUEST_DIR, FAP_RESPONSE_DIR, load, load_script

sync = load_script("sync_contract_fixtures")
generate = load_script("generate_fap_fixtures")
API_KEY = "nova-contract-test-key"  # synthetic credential, never a real one


def test_the_nova_copy_is_exactly_what_its_manifest_pins() -> None:
    assert sync.verify_copy(FAP_RESPONSE_DIR) == []


@pytest.mark.skipif(
    not os.environ.get("CONTRACT_SOURCE_NOVA"),
    reason="set CONTRACT_SOURCE_NOVA=<NOVA>/contracts/fap_response",
)
def test_the_nova_copy_is_identical_to_the_nova_source() -> None:
    assert sync.differences(Path(os.environ["CONTRACT_SOURCE_NOVA"]), FAP_RESPONSE_DIR) == []


def test_nova_answered_the_requests_this_repository_holds() -> None:
    """NOVA's responses were produced from the very request bodies FORGE generates (hash of the request manifest)."""
    manifest = load(FAP_RESPONSE_DIR, "manifest.json")
    assert manifest["derived_from"]["fap_request_manifest_sha256"] == sync.digest(
        FAP_REQUEST_DIR / "manifest.json"
    ), "NOVA answered another version of the FAP request: refresh both copies (docs/CONTRACTS.md)"
    assert manifest["protocol"] == "forge-agent-protocol/v1"


async def invoke(name: str) -> tuple[Any, InMemoryTraceRecorder, respx.Route]:
    fixture = load(FAP_RESPONSE_DIR, name)
    request_body = load(FAP_REQUEST_DIR, "request_orbit_live.json")
    request = generate._request({"source": "scenario"})
    request.context = {
        key: value for key, value in request_body["context"].items() if key != "max_classification"
    }
    request.agent.credentials = {"api_key": API_KEY}
    recorder = InMemoryTraceRecorder()
    with respx.mock as mock:
        route = mock.post(f"{generate.NOVA_URL}/v1/agents/nova-orchestrator/runs").mock(
            return_value=httpx.Response(fixture["status_code"], json=fixture["body"])
        )
        try:
            result = await get_adapter("nova").invoke(request, recorder)
        except AgentExecutionError as error:
            return error, recorder, route
    return result, recorder, route


async def test_a_successful_run_is_read_with_its_events_usage_and_versions() -> None:
    result, recorder, route = await invoke("response_ok.json")
    body = load(FAP_RESPONSE_DIR, "response_ok.json")["body"]
    assert route.calls.last.request.headers["authorization"] == f"Bearer {API_KEY}"
    assert (
        result.output_text == body["output"]
        and "[source: 3bc8be0b-0000-4000-8000-000000000001]" in result.output_text
    )
    assert result.token_usage.input_tokens == 100 and result.token_usage.output_tokens == 20
    assert {e.type for e in recorder.events} >= {TraceEventType.retrieval, TraceEventType.llm_call}
    assert result.metadata["nova_agent_id"] == "nova-orchestrator"
    # What FORGE needs to tell the declared version from the executed one is in the response.
    meta = body["metadata"]
    assert (
        meta["requested_version"]
        and meta["executed_version"]
        and meta["executed"]["version"] == meta["executed_version"]
    )


async def test_a_version_change_is_a_permanent_failure_that_names_the_field() -> None:
    error, _, _ = await invoke("response_unsupported_override.json")
    assert isinstance(error, AgentExecutionError) and not error.retryable
    assert (
        "422" in str(error)
        and "Surcharge non prise en charge" in str(error)
        and "agent.version" in str(error)
    )
    assert API_KEY not in str(error)


async def test_a_wrong_credential_is_a_permanent_failure_without_leaking_the_key() -> None:
    error, _, _ = await invoke("response_unauthorized.json")
    assert isinstance(error, AgentExecutionError) and not error.retryable
    assert "refusé l'authentification" in str(error) and "401" in str(error) and API_KEY not in str(error)


async def test_a_context_above_the_ceiling_is_a_permanent_refusal() -> None:
    error, _, _ = await invoke("response_classification_refused.json")
    assert isinstance(error, AgentExecutionError) and not error.retryable
    assert "403" in str(error) and "classification" in str(error)
