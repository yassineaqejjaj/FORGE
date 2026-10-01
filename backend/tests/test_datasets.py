"""Datasets: context documents and gold runs, items add / remove, version bump."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role
from tests.factories import create_agent_version, create_run, create_scenario_version


async def test_context_dataset_lifecycle(client_as) -> None:
    editor = await client_as(Role.editor)
    slug = f"docs-{uuid.uuid4().hex[:6]}"
    created = await editor.post(
        "/api/v1/datasets",
        json={
            "name": "Documentation produit",
            "slug": slug,
            "kind": "context",
            "items": [{"title": "Guide d'export", "content": "Le bouton Exporter…", "source": "wiki"}],
        },
    )
    assert created.status_code == 201, created.text
    dataset = created.json()
    assert dataset["version"] == 1 and dataset["items_count"] == 1
    assert dataset["items"][0]["key"] == "guide-d-export"
    assert dataset["items"][0]["content"] == {
        "title": "Guide d'export", "content": "Le bouton Exporter…", "source": "wiki", "metadata": {},
    }  # fmt: skip

    added = await editor.post(
        f"/api/v1/datasets/{dataset['id']}/items",
        json={"items": [{"key": "faq", "title": "FAQ", "content": "Questions", "metadata": {"lang": "fr"}}]},
    )
    assert added.status_code == 201 and added.json()[0]["key"] == "faq"
    duplicate = await editor.post(f"/api/v1/datasets/{dataset['id']}/items", json={"items": [{"key": "faq", "content": "x"}]})
    assert duplicate.status_code == 409
    empty = await editor.post(f"/api/v1/datasets/{dataset['id']}/items", json={"items": [{"title": "Sans contenu"}]})
    assert empty.status_code == 422

    detail = (await editor.get(f"/api/v1/datasets/{dataset['id']}")).json()
    assert detail["version"] == 2 and [i["key"] for i in detail["items"]] == ["guide-d-export", "faq"]
    removed = await editor.delete(f"/api/v1/datasets/{dataset['id']}/items/{detail['items'][0]['id']}")
    assert removed.status_code == 204
    assert (await editor.delete(f"/api/v1/datasets/{dataset['id']}/items/{uuid.uuid4()}")).status_code == 404

    patched = await editor.patch(f"/api/v1/datasets/{dataset['id']}", json={"description": "Docs", "tags": ["prd"]})
    assert patched.json()["description"] == "Docs" and patched.json()["version"] == 3

    listing = (await editor.get("/api/v1/datasets", params={"kind": "context", "q": slug})).json()
    assert listing["total"] == 1 and listing["items"][0]["items_count"] == 1
    assert (await editor.post("/api/v1/datasets", json={"name": "x", "slug": slug, "kind": "gold"})).status_code == 409

    viewer = await client_as(Role.viewer)
    assert (await viewer.get(f"/api/v1/datasets/{dataset['id']}")).status_code == 200
    assert (await viewer.post("/api/v1/datasets", json={"name": "x", "kind": "context"})).status_code == 403


async def test_gold_dataset_references_runs(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av)
    await db_session.commit()
    editor = await client_as(Role.editor)
    created = await editor.post(
        "/api/v1/datasets",
        json={"name": f"Gold {uuid.uuid4().hex[:6]}", "kind": "gold", "items": [{"run_id": str(run.id), "notes": "cas limite"}]},
    )
    assert created.status_code == 201, created.text
    item = created.json()["items"][0]
    assert item["run_id"] == str(run.id) and item["content"] == {"notes": "cas limite"}
    assert item["run"]["status"] == "pending" and item["run"]["agent_label"].endswith("v1.0")
    missing = await editor.post(f"/api/v1/datasets/{created.json()['id']}/items", json={"items": [{"run_id": str(uuid.uuid4())}]})
    assert missing.status_code == 422
    no_run = await editor.post(f"/api/v1/datasets/{created.json()['id']}/items", json={"items": [{"notes": "x"}]})
    assert no_run.status_code == 422
