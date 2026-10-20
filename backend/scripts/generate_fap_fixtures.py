"""Generate the FAP request fixtures NOVA reads (NOV-74): ORBIT fixture -> real FORGE code -> request body.

    uv run python scripts/generate_fap_fixtures.py          # rewrite contracts/fap_request/*.json
    uv run python scripts/generate_fap_fixtures.py --check  # exit 1 when the committed files are stale

Read-only with respect to the code: for each scenario, ORBIT is answered (respx, no network) with the ORBIT
contract copy in ``tests/fixtures/orbit``; the real ``prepare_context`` + ``NovaAdapter.invoke`` run, and the
request body FORGE sends to NOVA is captured as it goes on the wire. Synthetic data only. NOVA keeps a
verified copy (docs/CONTRACTS.md); ``manifest.json`` records the ORBIT contract the bodies derive from.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("FORGE_ENV", "test")  # settings are read at import time; nothing here needs a database

import httpx  # noqa: E402
import respx  # noqa: E402

from forge.adapters.base import HEADER_ATTEMPT, HEADER_REPETITION, HEADER_RUN_ID  # noqa: E402
from forge.adapters.registry import get_adapter  # noqa: E402
from forge.domain.enums import AdapterKind, Difficulty, ScenarioVisibility  # noqa: E402
from forge.domain.traces.protocol import FAP_VERSION  # noqa: E402
from forge.domain.traces.recorder import InMemoryTraceRecorder  # noqa: E402
from forge.domain.types import AgentRequest, AgentSpec, ScenarioSpec  # noqa: E402
from forge.services.context_providers import prepare_context  # noqa: E402

ORBIT_DIR = BACKEND / "tests" / "fixtures" / "orbit"
CONTRACTS_DIR = BACKEND.parent / "contracts" / "fap_request"
MANIFEST = "manifest.json"
ORBIT_URL = "https://orbit.contract.invalid"
NOVA_URL = "https://nova.contract.invalid"
AGENT_VERSION = "0.1.0+contract.000000"  # label of a NOVA version registered in FORGE (synthetic)
#: file -> (context source, ORBIT fixture)
SCENARIOS = {
    "request_orbit_live.json": ("orbit_live", "context_package.json"),
    "request_orbit_live_limited_rights.json": ("orbit_live", "context_package_limited_rights.json"),
    "request_orbit_snapshot.json": ("orbit_snapshot", "snapshot.json"),
}


def _request(context: dict[str, Any]) -> AgentRequest:
    scenario = ScenarioSpec(
        scenario_id="scn-1", scenario_version_id="scv-1", slug="prd", name="PRD", version=1,
        category="product_management", difficulty=Difficulty.medium, visibility=ScenarioVisibility.public,
        classification=1, input={"prompt": "Rédige un PRD pour l'export CSV."},
        constraints=["Maximum 300 mots"], expected_output="NEVER-SENT-TO-THE-AGENT",
    )  # fmt: skip
    agent = AgentSpec(
        agent_id="agt-1", agent_version_id="agv-1", agent_name="NOVA", agent_slug="nova",
        version=AGENT_VERSION, adapter_kind=AdapterKind.nova, endpoint=NOVA_URL,
        adapter_config={"nova_agent_id": "nova-orchestrator"}, context_config=context,
    )  # fmt: skip
    return AgentRequest(
        run_id="run-contract-1", scenario=scenario, agent=agent, context={}, otel_trace_id="a" * 32,
        trace_headers={HEADER_RUN_ID: "run-contract-1", HEADER_REPETITION: "0", HEADER_ATTEMPT: "1"},
    )  # fmt: skip


async def _body(source: str, orbit_fixture: str) -> dict[str, Any]:
    """The request FORGE sends to NOVA for one ORBIT answer (real code, ORBIT and NOVA answered by respx)."""
    answer = json.loads((ORBIT_DIR / orbit_fixture).read_text(encoding="utf-8"))
    orbit = {"project": "acme", "base_url": ORBIT_URL, "snapshot": "discovery"}
    request = _request({"source": source, "orbit": orbit})
    with respx.mock(assert_all_called=True) as mock:
        if source == "orbit_snapshot":
            mock.get(f"{ORBIT_URL}/api/v1/projects/acme/snapshots/discovery/latest").mock(
                return_value=httpx.Response(200, json=answer)
            )
        else:
            mock.post(f"{ORBIT_URL}/api/v1/projects/acme/context").mock(
                return_value=httpx.Response(200, json=answer)
            )
        prepared = await prepare_context(None, request.scenario, request.agent, run_id="run-contract-1")  # type: ignore[arg-type]
        request.context = prepared.context
        nova = mock.post(f"{NOVA_URL}/v1/agents/nova-orchestrator/runs").mock(
            return_value=httpx.Response(200, json={"protocol": FAP_VERSION, "output": "ok"})
        )
        await get_adapter("nova").invoke(request, InMemoryTraceRecorder())
        return json.loads(nova.calls.last.request.content)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build() -> dict[str, str]:
    """``{file name: content}`` of the whole directory, manifest included."""
    files = {
        name: json.dumps(asyncio.run(_body(source, fixture)), indent=1, ensure_ascii=False) + "\n"
        for name, (source, fixture) in SCENARIOS.items()
    }
    orbit_manifest = (ORBIT_DIR / MANIFEST).read_bytes()
    manifest = {
        "contract": "fap-request",
        "protocol": FAP_VERSION,
        "source": "FORGE backend/scripts/generate_fap_fixtures.py (real code, synthetic data)",
        "derived_from": {
            "orbit_manifest_sha256": hashlib.sha256(orbit_manifest).hexdigest(),
            "orbit_schema_version": json.loads(orbit_manifest)["schema_version"],
            "scenarios": {name: fixture for name, (_, fixture) in SCENARIOS.items()},
        },
        "files": {name: {"sha256": sha256(text)} for name, text in sorted(files.items())},
    }
    files[MANIFEST] = json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"
    return files


def main(argv: list[str]) -> int:
    expected = build()
    if "--check" in argv:
        stale = [
            name
            for name, text in expected.items()
            if not (CONTRACTS_DIR / name).is_file()
            or (CONTRACTS_DIR / name).read_text(encoding="utf-8") != text
        ]
        if stale:
            print(
                f"contracts/fap_request is stale ({', '.join(stale)}): run scripts/generate_fap_fixtures.py"
            )
            return 1
        print("contracts/fap_request is up to date")
        return 0
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in expected.items():
        (CONTRACTS_DIR / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(expected)} files to {CONTRACTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
