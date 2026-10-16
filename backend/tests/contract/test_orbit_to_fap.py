"""ORBIT -> FORGE -> NOVA, FORGE's part (NOV-74): real ORBIT answers in, the request FORGE sends to NOVA out.

No service: ORBIT and NOVA are answered by respx with the contract fixtures. The same bodies are read by NOVA's
own contract tests (``tests/contract`` in the NOVA repository) from a verified copy.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from forge.services.context_providers import ContextPreparationError, prepare_context
from tests.contract.support import FAP_REQUEST_DIR, ORBIT_DIR, load, load_script

sync = load_script("sync_contract_fixtures")
generate = load_script("generate_fap_fixtures")


# --- The fixtures themselves ------------------------------------------------------------------------------------------


def test_the_orbit_copy_is_exactly_what_its_manifest_pins() -> None:
    assert sync.verify_copy(ORBIT_DIR) == []


@pytest.mark.skipif(
    not os.environ.get("CONTRACT_SOURCE_ORBIT"), reason="set CONTRACT_SOURCE_ORBIT=<ORBIT>/contracts/orbit"
)
def test_the_orbit_copy_is_identical_to_the_orbit_source() -> None:
    assert sync.differences(Path(os.environ["CONTRACT_SOURCE_ORBIT"]), ORBIT_DIR) == []


def test_the_fap_request_fixtures_derive_from_this_orbit_copy() -> None:
    manifest = load(FAP_REQUEST_DIR, "manifest.json")
    assert manifest["derived_from"]["orbit_manifest_sha256"] == sync.digest(ORBIT_DIR / "manifest.json"), (
        "refresh contracts/fap_request: `uv run python scripts/generate_fap_fixtures.py`"
    )
    assert (
        manifest["derived_from"]["orbit_schema_version"] == load(ORBIT_DIR, "manifest.json")["schema_version"]
    )
    assert sync.verify_copy(FAP_REQUEST_DIR) == []


def test_the_fap_request_fixtures_are_what_forge_produces_today() -> None:
    """Fails when ``orbit_documents`` / ``_merge`` / ``build_protocol_body`` / the NOVA adapter change the wire body."""
    expected = generate.build()
    assert {p.name for p in FAP_REQUEST_DIR.glob("*.json")} == set(expected)
    for name, text in expected.items():
        assert (FAP_REQUEST_DIR / name).read_text(encoding="utf-8") == text, (
            f"contracts/fap_request/{name} is stale: run `uv run python scripts/generate_fap_fixtures.py` "
            "and refresh the copy in NOVA (docs/CONTRACTS.md)"
        )


# --- Traversal: ORBIT answer -> FAP body ------------------------------------------------------------------------------


_live: dict[str, str] = {}


def body(name: str) -> dict[str, Any]:
    """The body FORGE produces *now* (the committed copy is checked equal to it above): behaviour, not a snapshot."""
    if not _live:
        _live.update(generate.build())
    return json.loads(_live[name])


def served(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in items if not i.get("forgotten")]


def test_real_context_reaches_nova_with_identical_passages_levels_and_sources() -> None:
    package, request = load(ORBIT_DIR, "context_package.json"), body("request_orbit_live.json")
    documents = request["context"]["documents"]
    assert [d["content"] for d in documents] == [i["excerpt"] for i in package["items"]]
    assert all(d["content"].strip() for d in documents)
    assert (
        [d["classification"] for d in documents]
        == [i["classification"] for i in package["items"]]
        == [1, 2, 3]
    )
    for doc, item in zip(documents, package["items"], strict=True):
        assert (doc["id"], doc["title"], doc["citation"], doc["version"]) == (
            item["id"], item["title"], item["citation"], item["version"],
        )  # fmt: skip
        assert (
            doc.get("document_id") == item["document_id"]
            and doc.get("memory_item_id") == item["memory_item_id"]
        )
    assert request["context"]["orbit_context"] == package["context"]
    assert request["context"]["max_classification"] == package["max_classification"] == 3


def test_a_secret_document_stays_secret_and_raises_the_declared_maximum() -> None:
    request = body("request_orbit_live.json")
    secret = next(d for d in request["context"]["documents"] if "C3" in d["title"])
    assert secret["classification"] == 3 and request["context"]["max_classification"] == 3


def test_limited_rights_never_send_what_the_reader_could_not_see() -> None:
    limited = load(ORBIT_DIR, "context_package_limited_rights.json")
    request = body("request_orbit_live_limited_rights.json")
    assert [d["classification"] for d in request["context"]["documents"]] == [1]
    assert request["context"]["max_classification"] == limited["max_classification"] == 1
    sent = json.dumps(request, ensure_ascii=False)
    assert "120 EUR" not in sent and "Décision : export CSV" not in sent  # the C2 and C3 passages
    assert limited["excluded"] and len(request["context"]["documents"]) == len(limited["items"])


def test_a_forgotten_snapshot_item_is_never_sent() -> None:
    snapshot, request = load(ORBIT_DIR, "snapshot.json"), body("request_orbit_snapshot.json")
    forgotten = [i for i in snapshot["items"] if i["forgotten"]]
    assert forgotten
    sent = json.dumps(request, ensure_ascii=False)
    assert all(i["id"] not in [d["id"] for d in request["context"]["documents"]] for i in forgotten)
    assert "contenu oublié" not in sent
    documents = request["context"]["documents"]
    assert [d["content"] for d in documents] == [i["excerpt"] for i in served(snapshot["items"])]
    assert [d["classification"] for d in documents] == [1, 2, 3]  # the snapshot carries levels since schema 2
    assert [d["id"] for d in documents] == [i["id"] for i in served(snapshot["items"])]
    assert (
        request["context"]["orbit_context"] == snapshot["content"]
        and request["context"]["max_classification"] == 3
    )


def test_what_the_agent_must_not_see_is_not_in_the_body() -> None:
    for name in generate.SCENARIOS:
        text = json.dumps(body(name), ensure_ascii=False)
        assert "NEVER-SENT-TO-THE-AGENT" not in text, name
        data = body(name)
        assert data["protocol"] == "forge-agent-protocol/v1" and data["nova_agent_id"] == "nova-orchestrator"


# --- ORBIT answers that are not contexts ------------------------------------------------------------------------------


@respx.mock
async def test_a_wrong_orbit_credential_fails_the_context_without_leaking_the_key() -> None:
    respx.post("https://orbit.contract.invalid/api/v1/projects/acme/context").mock(
        return_value=httpx.Response(401, json={"detail": "Identifiants invalides", "code": "unauthorized"})
    )
    request = generate._request(
        {"source": "orbit_live", "orbit": {"project": "acme", "base_url": generate.ORBIT_URL}}
    )
    with pytest.raises(ContextPreparationError) as error:
        await prepare_context(None, request.scenario, request.agent)  # type: ignore[arg-type]
    assert not error.value.retryable and "ORBIT" in str(error.value)


@respx.mock
async def test_an_optional_orbit_context_falls_back_to_the_scenario_context() -> None:
    respx.post("https://orbit.contract.invalid/api/v1/projects/acme/context").mock(
        return_value=httpx.Response(403, json={})
    )
    orbit = {"project": "acme", "base_url": generate.ORBIT_URL, "optional": True}
    request = generate._request({"source": "orbit_live", "orbit": orbit})
    prepared = await prepare_context(
        None,
        request.scenario,
        request.agent,
        base_context={"documents": [{"id": "s1", "content": "Scénario."}]},  # type: ignore[arg-type]
    )
    assert prepared.source.value == "scenario" and prepared.warnings
    assert [d["id"] for d in prepared.context["documents"]] == ["s1"]


# --- Additive field of ORBIT NOV-106 ------------------------------------------------------------------------------------

ORBIT_PROJECT_ID = "0a0b0c0d-0000-4000-8000-000000000106"  # synthetic ``orion_project_id`` of the fixtures


def test_the_orion_project_id_is_an_additive_field_forge_tolerates_and_does_not_forward() -> None:
    """ORBIT NOV-106 adds ``orion_project_id`` to every contract answer; nothing FORGE reads changes."""
    for name in ("context_package.json", "context_package_limited_rights.json", "snapshot.json"):
        assert load(ORBIT_DIR, name)["orion_project_id"] == ORBIT_PROJECT_ID, name
    for name in generate.SCENARIOS:
        assert ORBIT_PROJECT_ID not in json.dumps(body(name)), (
            name
        )  # not part of FAP v1: not sent to the agent
