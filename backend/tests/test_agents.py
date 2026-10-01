"""Agent Registry: agents, immutable versions (inline / base + overrides), 409, diff, contamination."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role, ScenarioVisibility
from tests.factories import create_scenario_version


def _slug() -> str:
    return f"agent-{uuid.uuid4().hex[:8]}"


MODEL = {"provider": "openai", "model": "gpt-5-mini", "temperature": 0.2, "input_cost_per_mtok": 0.25}
TOOLS = [
    {
        "name": "search_docs",
        "description": "Recherche dans la documentation",
        "parameters": {"type": "object"},
    },
    {"name": "create_ticket", "description": "Crée un ticket"},
]


async def _agent(c) -> dict:
    response = await c.post(
        "/api/v1/agents",
        json={"name": "Product Agent", "slug": _slug(), "provider": "NOVA", "tags": ["pm", "pm", "demo"]},
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_agent_crud(client_as) -> None:
    editor = await client_as(Role.editor)
    agent = await _agent(editor)
    assert (
        agent["tags"] == ["pm", "demo"] and agent["versions_count"] == 0 and agent["latest_version"] is None
    )
    duplicate = await editor.post("/api/v1/agents", json={"name": "x", "slug": agent["slug"]})
    assert duplicate.status_code == 409
    auto = await editor.post("/api/v1/agents", json={"name": f"Agent Étoilé {uuid.uuid4().hex[:4]}"})
    assert auto.json()["slug"].startswith("agent-etoile-")

    patched = await editor.patch(
        f"/api/v1/agents/{agent['id']}", json={"description": "PM", "metadata": {"team": "x"}}
    )
    assert patched.json()["description"] == "PM" and patched.json()["metadata"] == {"team": "x"}

    listing = await editor.get("/api/v1/agents", params={"q": agent["slug"]})
    assert listing.json()["total"] == 1
    archived = await editor.patch(f"/api/v1/agents/{agent['id']}", json={"archived": True})
    assert archived.json()["archived"] is True
    assert (await editor.get("/api/v1/agents", params={"q": agent["slug"]})).json()["total"] == 0
    assert (await editor.get("/api/v1/agents", params={"q": agent["slug"], "archived": True})).json()[
        "total"
    ] == 1
    assert (await editor.get(f"/api/v1/agents/{uuid.uuid4()}")).status_code == 404

    viewer = await client_as(Role.viewer)
    assert (await viewer.get(f"/api/v1/agents/{agent['id']}")).status_code == 200
    assert (await viewer.post("/api/v1/agents", json={"name": "x"})).status_code == 403


async def test_versions_inline_configs_and_conflict(client_as) -> None:
    editor = await client_as(Role.editor)
    agent = await _agent(editor)
    prompt_name = f"pm_{uuid.uuid4().hex[:6]}"
    body = {
        "adapter_kind": "openai",
        "model": MODEL,
        "system_prompt": "Tu es un product manager. Réponds à {{question}}.",
        "prompt_name": prompt_name,
        "tools": TOOLS,
        "budget": {"max_tokens": 4000, "max_steps": 4},
        "changelog": "Première version",
    }
    created = await editor.post(f"/api/v1/agents/{agent['id']}/versions", json=body)
    assert created.status_code == 201, created.text
    v1 = created.json()
    assert v1["version"] == "1.0" and v1["label"] == "Product Agent v1.0"
    assert v1["model_configuration"]["model"] == "gpt-5-mini"
    assert v1["prompt"]["name"] == prompt_name and v1["prompt"]["version"] == 1
    assert [t["name"] for t in v1["tools"]] == ["search_docs", "create_ticket"]
    assert v1["tool_configuration"]["name"] == f"{agent['slug']}-tools"
    assert v1["budget"]["max_tokens"] == 4000 and v1["budget"]["timeout_seconds"] is None
    assert v1["content_hash"].startswith("sha256:") and v1["contamination"] == []

    identical = await editor.post(f"/api/v1/agents/{agent['id']}/versions", json=body)
    assert identical.status_code == 409 and "identique" in identical.json()["detail"]

    # Model configuration was reused (content-addressed), prompt version reused.
    models = (await editor.get("/api/v1/model-configurations", params={"q": "gpt-5-mini"})).json()
    assert sum(1 for m in models["items"] if m["id"] == v1["model_configuration"]["id"]) == 1
    prompts = (await editor.get(f"/api/v1/prompts/{prompt_name}/versions")).json()
    assert len(prompts) == 1 and prompts[0]["variables"] == ["question"]

    # Improvement loop: base version + overrides, auto label bump.
    v2 = await editor.post(
        f"/api/v1/agents/{agent['id']}/versions",
        json={
            "base_version_id": v1["id"],
            "system_prompt": "Tu es un product manager senior. Cite tes sources.",
            "prompt_name": prompt_name,
            "changelog": "Feedback : sources",
        },
    )
    assert v2.status_code == 201, v2.text
    v2 = v2.json()
    assert v2["version"] == "1.1" and v2["parent_version_id"] == v1["id"]
    assert v2["prompt"]["version"] == 2 and v2["model_configuration"]["id"] == v1["model_configuration"]["id"]
    assert v2["tool_configuration"]["id"] == v1["tool_configuration"]["id"]

    versions = (await editor.get(f"/api/v1/agents/{agent['id']}/versions")).json()
    assert [v["version"] for v in versions] == ["1.1", "1.0"] and versions[0]["model"] == "gpt-5-mini"
    detail = (await editor.get(f"/api/v1/agents/{agent['id']}")).json()
    assert detail["versions_count"] == 2 and detail["latest_version"]["version"] == "1.1"

    labelled = await editor.post(
        f"/api/v1/agents/{agent['id']}/versions",
        json={"base_version_id": v2["id"], "version": "1.1", "budget": {"max_steps": 6}},
    )
    assert labelled.status_code == 409


async def test_version_validation(client_as) -> None:
    editor = await client_as(Role.editor)
    agent = await _agent(editor)
    url = f"/api/v1/agents/{agent['id']}/versions"
    assert (await editor.post(url, json={})).status_code == 422  # adapter kind required
    assert (await editor.post(url, json={"adapter_kind": "openai"})).status_code == 422  # model required
    assert (
        await editor.post(url, json={"adapter_kind": "custom_api"})
    ).status_code == 422  # endpoint required
    both = await editor.post(
        url, json={"adapter_kind": "mock", "model": MODEL, "model_configuration_id": str(uuid.uuid4())}
    )
    assert both.status_code == 422
    missing = await editor.post(url, json={"adapter_kind": "mock", "credential_id": str(uuid.uuid4())})
    assert missing.status_code == 404
    bad_budget = await editor.post(url, json={"adapter_kind": "mock", "budget": {"max_steps": 0}})
    assert bad_budget.status_code == 422
    dup_tools = await editor.post(url, json={"adapter_kind": "mock", "tools": [TOOLS[0], TOOLS[0]]})
    assert dup_tools.status_code == 422
    other = await _agent(editor)
    base = (await editor.post(f"/api/v1/agents/{other['id']}/versions", json={"adapter_kind": "mock"})).json()
    cross = await editor.post(url, json={"base_version_id": base["id"]})
    assert cross.status_code == 422


async def test_diff_between_versions(client_as) -> None:
    editor = await client_as(Role.editor)
    agent = await _agent(editor)
    url = f"/api/v1/agents/{agent['id']}/versions"
    v1 = (
        await editor.post(
            url, json={"adapter_kind": "mock", "system_prompt": "Ligne A\nLigne B\n", "tools": TOOLS[:1]}
        )
    ).json()
    v2 = (
        await editor.post(
            url,
            json={
                "base_version_id": v1["id"],
                "system_prompt": "Ligne A\nLigne C\n",
                "tools": [{**TOOLS[0], "description": "Nouvelle description"}, TOOLS[1]],
                "adapter_config": {"script": {"output": "ok"}},
            },
        )
    ).json()
    diff = await editor.get(f"/api/v1/agent-versions/{v2['id']}/diff")
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["against_version_id"] == v1["id"] and body["same_content_hash"] is False
    fields = {c["field"] for c in body["changes"]}
    assert {"system_prompt", "tools", "adapter_config", "tool_configuration"} <= fields
    assert "-Ligne B" in body["prompt_diff"] and "+Ligne C" in body["prompt_diff"]
    assert body["tools_diff"] == {"added": ["create_ticket"], "removed": [], "changed": ["search_docs"]}
    explicit = await editor.get(f"/api/v1/agent-versions/{v1['id']}/diff", params={"against": v2["id"]})
    assert explicit.json()["tools_diff"]["removed"] == ["create_ticket"]
    assert (await editor.get(f"/api/v1/agent-versions/{v1['id']}/diff")).status_code == 404


async def test_contamination_warnings(client_as, db_session) -> None:
    secret_output = (
        "La feuille de route confidentielle prévoit le lancement du module de facturation au troisième trimestre "
        "avec une migration progressive des clients existants vers la nouvelle offre tarifaire."
    )
    sv = await create_scenario_version(
        db_session, visibility=ScenarioVisibility.private, expected_output=secret_output
    )
    await db_session.commit()
    editor = await client_as(Role.editor)
    agent = await _agent(editor)
    created = await editor.post(
        f"/api/v1/agents/{agent['id']}/versions",
        json={"adapter_kind": "mock", "system_prompt": f"Réponds : {secret_output} Canari : {sv.canary}"},
    )
    assert created.status_code == 201, created.text
    warnings = created.json()["contamination"]
    assert {w["type"] for w in warnings} == {"canary", "ngram_overlap"}
    assert all(w["location"] == "system_prompt" for w in warnings)
    assert "facturation" not in str(warnings)
    summary = (await editor.get(f"/api/v1/agents/{agent['id']}")).json()["latest_version"]
    assert summary["contamination_warnings"] == 2


async def test_prompts_and_configurations_endpoints(client_as) -> None:
    editor = await client_as(Role.editor)
    name = f"support_{uuid.uuid4().hex[:6]}"
    first = await editor.post("/api/v1/prompts", json={"name": name, "content": "Bonjour {{client}}"})
    assert first.status_code == 201 and first.json()["version"] == 1
    assert (
        await editor.post("/api/v1/prompts", json={"name": name, "content": "Bonjour {{client}}"})
    ).status_code == 409
    second = await editor.post("/api/v1/prompts", json={"name": name, "content": "Salut {{client}}"})
    assert second.json()["version"] == 2
    listing = (await editor.get("/api/v1/prompts", params={"q": name})).json()
    assert listing == [
        {
            "name": name,
            "latest_version": 2,
            "versions_count": 2,
            "latest_version_id": second.json()["id"],
            "description": "",
            "content_hash": second.json()["content_hash"],
            "updated_at": second.json()["created_at"],
        }
    ]
    assert (await editor.get("/api/v1/prompts/inconnu_xyz/versions")).status_code == 404
    assert (
        await editor.post("/api/v1/prompts", json={"name": "Bad Name", "content": "x"})
    ).status_code == 422

    model = await editor.post(
        "/api/v1/model-configurations", json={**MODEL, "model": f"m-{uuid.uuid4().hex[:6]}"}
    )
    again = await editor.post("/api/v1/model-configurations", json={**model.json(), "id": None})
    assert model.status_code == 201 and again.json()["id"] == model.json()["id"]

    tools_name = f"tools_{uuid.uuid4().hex[:6]}"
    tc = await editor.post("/api/v1/tool-configurations", json={"name": tools_name, "tools": TOOLS})
    assert tc.status_code == 201 and tc.json()["version"] == 1
    assert (
        await editor.post("/api/v1/tool-configurations", json={"name": tools_name, "tools": TOOLS})
    ).status_code == 409
    listed = (await editor.get("/api/v1/tool-configurations", params={"name": tools_name})).json()
    assert listed["total"] == 1
    agent = await _agent(editor)
    version = await editor.post(
        f"/api/v1/agents/{agent['id']}/versions",
        json={
            "adapter_kind": "mock",
            "tool_configuration_id": tc.json()["id"],
            "prompt_version_id": second.json()["id"],
        },
    )
    assert version.status_code == 201
    assert version.json()["system_prompt"] == "Salut {{client}}" and len(version.json()["tools"]) == 2


async def test_test_endpoint_maps_execution_errors(client_as) -> None:
    editor = await client_as(Role.editor)
    agent = await _agent(editor)
    version = (
        await editor.post(
            f"/api/v1/agents/{agent['id']}/versions",
            json={"adapter_kind": "mock", "adapter_config": {"script": {"output": "Réponse de test"}}},
        )
    ).json()
    response = await editor.post(
        f"/api/v1/agent-versions/{version['id']}/test", json={"input": {"prompt": "Bonjour"}}
    )
    # 501 while the Agent Runner is not implemented, 200 once it is.
    assert response.status_code in (200, 501), response.text
    if response.status_code == 200:
        assert response.json()["agent_version_id"] == version["id"]
    viewer = await client_as(Role.viewer)
    assert (
        await viewer.post(f"/api/v1/agent-versions/{version['id']}/test", json={"input": {"prompt": "x"}})
    ).status_code == 403
