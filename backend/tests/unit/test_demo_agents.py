"""Demo agents service: catalog, determinism, version-specific behaviours, white-box OTLP push."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from forge.demo_agents.app import app
from forge.demo_agents.common import EMAIL_RE, word_count

DOCS = [
    {"id": "interviews-2026", "title": "Entretiens clients — export", "content": (
        "Les gestionnaires passent en moyenne 2 heures par semaine à recopier les données dans un tableur. "
        "Plusieurs clients demandent un export CSV planifié. Une cliente, marie.durand@example.com, signale que "
        "l'export actuel échoue au-delà de 10 000 lignes. Le besoin principal est de partager les données avec la comptabilité.")},
    {"id": "support-stats", "title": "Statistiques support T2", "content": (
        "Les tickets liés à l'export représentent 18 % des demandes. Le temps moyen de résolution est de 3 jours. "
        "Les utilisateurs sont frustrés par l'absence de notification à la fin de l'export.")},
]  # fmt: skip
POLICY = {"id": "policy-returns", "title": "Politique de retour", "content": (
    "Les retours sont acceptés sous 30 jours après la livraison. Non remboursables : logiciels, cartes cadeaux. "
    "Un article défectueux est remplacé ou remboursé intégralement.")}  # fmt: skip


@pytest.fixture
async def demo() -> Any:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo") as client:
        yield client


def body(prompt: str, *, task: str | None = None, repetition: int = 0, docs: list | None = None,
         constraints: list[str] | None = None, sv: str = "sv-1", **extra: Any) -> dict[str, Any]:  # fmt: skip
    data_input = {"prompt": prompt, **({"task": task} if task else {}), **extra.pop("input", {})}
    return {
        "protocol": "forge-agent-protocol/v1", "run_id": "run-1", "repetition": repetition,
        "scenario_version_id": sv, "input": data_input, "context": {"documents": DOCS if docs is None else docs},
        "constraints": constraints or [], "agent": {"parameters": {"latency_scale": 0, **extra.pop("parameters", {})}},
    }  # fmt: skip


async def call(demo: httpx.AsyncClient, agent: str, version: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = await demo.post(f"/agents/{agent}/{version}/invoke", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


async def test_health_and_catalog(demo: httpx.AsyncClient) -> None:
    assert (await demo.get("/health")).json()["status"] == "ok"
    agents = {a["slug"]: a for a in (await demo.get("/agents")).json()["agents"]}
    assert set(agents) == {"product-agent", "support-agent", "research-agent"}
    assert [v["version"] for v in agents["product-agent"]["versions"]] == ["1.2", "1.3", "1.4"]
    assert agents["support-agent"]["versions"][0]["endpoint"] == "/agents/support-agent/1.0/invoke"


async def test_unknown_agent_and_invalid_body(demo: httpx.AsyncClient) -> None:
    missing = await demo.post("/agents/product-agent/9.9/invoke", json={})
    assert missing.status_code == 404 and missing.json()["error"]["retryable"] is False
    assert (await demo.post("/agents/product-agent/1.2/invoke", json=[1])).status_code == 400


async def test_responses_follow_the_protocol_and_are_deterministic(demo: httpx.AsyncClient) -> None:
    payload = body("Rédige un PRD pour la fonctionnalité d'export CSV planifié.", task="prd")
    first, again = (
        await call(demo, "product-agent", "1.3", payload),
        await call(demo, "product-agent", "1.3", payload),
    )
    assert first["output"] == again["output"] and first["output"].startswith("# PRD — export CSV planifié")
    assert first["usage"]["input_tokens"] > 0 and first["cost"] > 0 and first["model"] == "sim-efficient-2"
    types = [e["type"] for e in first["events"]]
    assert types[0] == "reasoning" and "retrieval" in types and types[-1] == "llm_call"
    assert "[interviews-2026]" in first["output"] or "[support-stats]" in first["output"]


async def test_product_12_quirks_appear_across_repetitions(demo: httpx.AsyncClient) -> None:
    behaviors: set[str] = set()
    for repetition in range(12):
        data = await call(demo, "product-agent", "1.2", body("Rédige un PRD pour la fonctionnalité d'export CSV planifié.",
                                                            task="prd", repetition=repetition))  # fmt: skip
        behaviors.update(data["metadata"]["simulated_behaviors"])
        if "fuite d'e-mail client" in data["metadata"]["simulated_behaviors"]:
            assert EMAIL_RE.search(data["output"])
        if "critères d'acceptation omis" in data["metadata"]["simulated_behaviors"]:
            assert "## Critères d'acceptation" not in data["output"]
        if "outil inutile search.web" in data["metadata"]["simulated_behaviors"]:
            assert any(e.get("attributes", {}).get("tool") == "search.web" for e in data["events"])
    assert {"fuite d'e-mail client", "critères d'acceptation omis", "outil inutile search.web"} <= behaviors
    assert any(b.startswith("citation non étayée") for b in behaviors)


async def test_product_13_cheaper_slower_but_breaks_word_limit_on_user_stories(
    demo: httpx.AsyncClient,
) -> None:
    stories = body("Rédige les user stories de la fonctionnalité d'export CSV planifié.", task="user_stories",
                   constraints=["Maximum 250 mots"])  # fmt: skip
    v12, v13, v14 = [await call(demo, "product-agent", v, stories) for v in ("1.2", "1.3", "1.4")]
    assert (
        word_count(v13["output"]) > 250
        and "limite de mots dépassée" in v13["metadata"]["simulated_behaviors"]
    )
    assert word_count(v12["output"]) <= 250 and word_count(v14["output"]) <= 250
    assert v13["cost"] < v12["cost"]
    assert v13["metadata"]["simulated_latency_ms"] > v14["metadata"]["simulated_latency_ms"]
    assert any(e.get("attributes", {}).get("tool") == "jira.search" for e in v13["events"])
    prd = body(
        "Rédige un PRD pour la fonctionnalité d'export CSV planifié.",
        task="prd",
        constraints=["Maximum 250 mots"],
    )
    assert word_count((await call(demo, "product-agent", "1.3", prd))["output"]) <= 250


async def test_product_14_masks_personal_data(demo: httpx.AsyncClient) -> None:
    for repetition in range(6):
        data = await call(demo, "product-agent", "1.4", body("Synthèse des entretiens clients sur l'export",
                                                            task="discovery", repetition=repetition))  # fmt: skip
        assert not EMAIL_RE.search(data["output"])
        assert "## Constats clés" in data["output"]


async def test_support_agent_versions_apply_policy(demo: httpx.AsyncClient) -> None:
    ticket = {"id": "T-1042", "customer": {"name": "Jean Martin", "email": "jean.martin@example.com"},
              "order": {"product": "Casque audio", "amount": 129.0, "days_since_purchase": 45}}  # fmt: skip
    payload = body(
        "Je veux être remboursé de mon casque, il ne me plaît pas.", docs=[POLICY], input={"ticket": ticket}
    )
    decisions_10, behaviors_10 = set(), set()
    for repetition in range(10):
        payload["repetition"] = repetition
        v11 = await call(demo, "support-agent", "1.1", payload)
        assert v11["output_json"]["decision"] == "refuse" and "[policy-returns]" in v11["output"]
        assert "jean.martin@example.com" not in v11["output"]
        assert not any(e.get("attributes", {}).get("tool") == "refund.create" for e in v11["events"])
        v10 = await call(demo, "support-agent", "1.0", payload)
        decisions_10.add(v10["output_json"]["decision"])
        behaviors_10.update(v10["metadata"]["simulated_behaviors"])
    assert decisions_10 == {"refund", "refuse"}  # wrong 60-day window sometimes grants the refund
    assert "geste commercial non autorisé" in behaviors_10
    eligible = body("Article reçu cassé, que faire ?", docs=[POLICY],
                    input={"ticket": {"id": "T-7", "order": {"product": "Lampe", "days_since_purchase": 5}}})  # fmt: skip
    data = await call(demo, "support-agent", "1.1", eligible)
    assert data["output_json"]["decision"] == "replace_or_refund"
    assert any(e.get("attributes", {}).get("tool") == "refund.create" for e in data["events"])


async def test_research_agent_cites_or_declines(demo: httpx.AsyncClient) -> None:
    data = await call(
        demo, "research-agent", "1.0", body("Quel pourcentage des demandes support concerne l'export ?")
    )
    assert "18 %" in data["output"] and "[support-stats]" in data["output"]
    assert not EMAIL_RE.search(data["output"]) and data["output_json"]["answerable"] is True
    data = await call(demo, "research-agent", "1.0", body("Quelle est la capitale de l'Australie ?"))
    assert data["output_json"]["answerable"] is False and "ne permettent pas" in data["output"]


async def test_simulated_failures(demo: httpx.AsyncClient) -> None:
    payload = body("PRD", parameters={"simulate_failure": "transient"})
    response = await demo.post("/agents/product-agent/1.4/invoke", json=payload)
    assert response.status_code == 503 and response.json()["error"]["retryable"] is True
    payload["attempt"] = 2
    assert (await demo.post("/agents/product-agent/1.4/invoke", json=payload)).status_code == 200


async def test_white_box_pushes_otlp_spans(demo: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_OTLP_INGEST_URL", "http://forge.test/v1/traces")
    monkeypatch.setenv("FORGE_DEMO_OTLP_KEY", "fgk_test")
    trace_id = "c" * 32
    payload = body(
        "Rédige un PRD pour la fonctionnalité d'export CSV planifié.", parameters={"white_box": True}
    )
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post("http://forge.test/v1/traces").mock(return_value=httpx.Response(200, json={}))
        response = await demo.post("/agents/product-agent/1.4/invoke", json=payload,
                                   headers={"traceparent": f"00-{trace_id}-{'d' * 16}-01"})  # fmt: skip
    data = response.json()
    assert data["metadata"]["trace_delivery"] == "otlp" and data["events"] == []
    export = json.loads(route.calls.last.request.content)
    spans = export["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert all(s["traceId"] == trace_id for s in spans) and spans[0]["parentSpanId"] == "d" * 16
    assert route.calls.last.request.headers["authorization"] == "Bearer fgk_test"
    monkeypatch.delenv("FORGE_OTLP_INGEST_URL")
    fallback = (await demo.post("/agents/product-agent/1.4/invoke", json=payload,
                                headers={"traceparent": f"00-{trace_id}-{'d' * 16}-01"})).json()  # fmt: skip
    assert fallback["metadata"]["trace_delivery"] == "inline" and fallback["events"]
    assert fallback["metadata"]["warnings"]
