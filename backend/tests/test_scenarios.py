"""Scenario Manager: creation, validation, versions (409), metadata, variants, import / export."""

from __future__ import annotations

import json
import uuid

import yaml

from forge.domain.enums import Role

CONTENT = {
    "difficulty": "hard",
    "description": "Rédaction d'un PRD",
    "input": {"prompt": "Rédige un PRD pour l'export CSV des rapports."},
    "context": {
        "documents": [{"id": "D1", "title": "Besoin client", "content": "Les clients veulent exporter."}]
    },
    "constraints": ["Moins de 600 mots", "Citer les sources"],
    "expected_output": "Un PRD avec objectifs, périmètre, exigences et critères d'acceptation.",
    "criteria": [{"key": "quality.completeness", "weight": 2}, "quality.accuracy"],
    "rules": [
        {"type": "sections_present", "params": {"sections": ["Objectifs", "Périmètre"]}},
        {"type": "max_length", "params": {"words": 600}, "severity": "low"},
        {"type": "not_contains", "params": {"keywords": ["garanti"]}, "hidden": True},
    ],
}


def _slug(prefix: str = "scenario_test") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _create(c, **overrides) -> dict:
    body = {"slug": _slug(), "name": "PRD export CSV", "category": "product_management", "content": CONTENT}
    body.update(overrides)
    response = await c.post("/api/v1/scenarios", json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_and_read_scenario(client_as) -> None:
    editor = await client_as(Role.editor)
    scenario = await _create(editor, tags=["prd", "csv"])
    assert scenario["latest_version"] == 1 and scenario["difficulty"] == "hard"
    assert scenario["family_id"] == scenario["id"] and scenario["category_label"] == "Product Management"
    latest = scenario["latest"]
    assert [r["id"] for r in latest["rules"]] == ["R1", "R2", "R3"]
    assert latest["canary"] is None, "canary hidden to editors"
    assert latest["rules"][2]["params"] == {} and latest["rules"][2]["hidden"] is True  # hidden rule masked
    assert latest["rules"][0]["params"] == {"sections": ["Objectifs", "Périmètre"]}
    assert latest["criteria"][1] == {"key": "quality.accuracy"}
    assert scenario["versions"][0]["changelog"] == "Version initiale"

    maintainer = await client_as(Role.maintainer)
    detail = (await maintainer.get(f"/api/v1/scenarios/{scenario['id']}")).json()
    assert detail["latest"]["canary"].startswith("FORGE-CANARY-")
    assert detail["latest"]["rules"][2]["params"] == {"keywords": ["garanti"]}

    version = (await editor.get(f"/api/v1/scenario-versions/{latest['id']}")).json()
    assert version["input"] == CONTENT["input"] and version["redacted"] is False


async def test_slug_generation_and_conflicts(client_as) -> None:
    editor = await client_as(Role.editor)
    category = f"cat {uuid.uuid4().hex[:4]} research"
    first = await editor.post(
        "/api/v1/scenarios", json={"name": "A", "category": category, "content": CONTENT}
    )
    second = await editor.post(
        "/api/v1/scenarios", json={"name": "B", "category": category, "content": CONTENT}
    )
    a, b = first.json()["slug"], second.json()["slug"]
    assert a.startswith("scenario_c") and a.endswith("_001") and b.endswith("_002")
    dup = await editor.post(
        "/api/v1/scenarios", json={"slug": a, "name": "C", "category": "x", "content": CONTENT}
    )
    assert dup.status_code == 409
    bad = await editor.post(
        "/api/v1/scenarios", json={"slug": "Bad Slug", "name": "C", "category": "x", "content": CONTENT}
    )
    assert bad.status_code == 422


async def test_invalid_content_is_rejected_with_details(client_as) -> None:
    editor = await client_as(Role.editor)
    response = await editor.post(
        "/api/v1/scenarios",
        json={
            "name": "Invalide",
            "category": "analysis",
            "content": {
                "input": {},
                "rules": [{"type": "contains", "params": {}}],
                "criteria": ["style.tone"],
            },
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail.startswith("Scénario invalide") and "input" in detail


async def test_fresh_scenarios_get_a_default_expiry(client_as) -> None:
    editor = await client_as(Role.editor)
    scenario = await _create(editor, visibility="fresh")
    assert scenario["fresh_until"] and scenario["is_fresh"] is True


async def test_new_versions_and_conflict(client_as) -> None:
    editor = await client_as(Role.editor)
    scenario = await _create(editor)
    url = f"/api/v1/scenarios/{scenario['id']}/versions"
    identical = await editor.post(url, json={"content": {"constraints": CONTENT["constraints"]}})
    assert identical.status_code == 409
    created = await editor.post(
        url, json={"content": {"constraints": ["Moins de 300 mots"]}, "changelog": "Plus court"}
    )
    assert created.status_code == 201, created.text
    v2 = created.json()
    assert v2["version"] == 2 and v2["constraints"] == ["Moins de 300 mots"]
    assert v2["input"] == CONTENT["input"], "fields not given are kept from the latest version"
    versions = (await editor.get(url)).json()
    assert [v["version"] for v in versions] == [2, 1]
    detail = (await editor.get(f"/api/v1/scenarios/{scenario['id']}")).json()
    assert detail["latest_version"] == 2 and detail["latest"]["id"] == v2["id"]
    maintainer = await client_as(Role.maintainer)
    canaries = {v["canary"] for v in (await maintainer.get(url)).json()}
    assert len(canaries) == 2


async def test_metadata_patch_and_filters(client_as) -> None:
    editor = await client_as(Role.editor)
    tag = f"tag-{uuid.uuid4().hex[:6]}"
    scenario = await _create(editor, tags=[tag])
    patched = await editor.patch(
        f"/api/v1/scenarios/{scenario['id']}",
        json={"name": "Renommé", "tags": [tag, "autre"], "visibility": "fresh"},
    )
    assert patched.status_code == 200
    assert (
        patched.json()["name"] == "Renommé"
        and patched.json()["visibility"] == "fresh"
        and patched.json()["fresh_until"]
    )
    listing = (await editor.get("/api/v1/scenarios", params={"tag": tag})).json()
    assert [s["id"] for s in listing["items"]] == [scenario["id"]]
    assert (await editor.get("/api/v1/scenarios", params={"tag": tag, "difficulty": "easy"})).json()[
        "total"
    ] == 0
    assert (await editor.get("/api/v1/scenarios", params={"tag": tag, "visibility": "fresh"})).json()[
        "total"
    ] == 1
    assert (await editor.get("/api/v1/scenarios", params={"q": "Renommé", "tag": tag})).json()["total"] == 1
    await editor.patch(f"/api/v1/scenarios/{scenario['id']}", json={"archived": True})
    assert (await editor.get("/api/v1/scenarios", params={"tag": tag})).json()["total"] == 0
    assert (await editor.get("/api/v1/scenarios", params={"tag": tag, "archived": True})).json()["total"] == 1
    too_high = await editor.patch(f"/api/v1/scenarios/{scenario['id']}", json={"classification": 3})
    assert too_high.status_code == 403
    viewer = await client_as(Role.viewer)
    assert (await viewer.patch(f"/api/v1/scenarios/{scenario['id']}", json={"name": "x"})).status_code == 403


async def test_variants_share_the_family(client_as) -> None:
    editor = await client_as(Role.editor)
    parent = await _create(editor)
    response = await editor.post(
        f"/api/v1/scenarios/{parent['id']}/variants",
        json={"label": "Contexte court", "overrides": {"context": {}, "difficulty": "medium"}},
    )
    assert response.status_code == 201, response.text
    variant = response.json()
    assert variant["slug"] == f"{parent['slug']}_variant_contexte_court"
    assert variant["family_id"] == parent["family_id"] and variant["parent_scenario_id"] == parent["id"]
    assert variant["variant_label"] == "contexte_court" and variant["difficulty"] == "medium"
    assert variant["latest"]["context"] == {} and variant["latest"]["input"] == CONTENT["input"]
    family = (await editor.get("/api/v1/scenarios", params={"family": parent["family_id"]})).json()
    assert {s["id"] for s in family["items"]} == {parent["id"], variant["id"]}
    detail = (await editor.get(f"/api/v1/scenarios/{parent['id']}")).json()
    assert [m["id"] for m in detail["family"]] == [variant["id"]]
    again = await editor.post(f"/api/v1/scenarios/{parent['id']}/variants", json={"label": "contexte court"})
    assert again.status_code == 409


async def test_export_import_round_trip(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    tag = f"exp-{uuid.uuid4().hex[:6]}"
    parent = await _create(maintainer, tags=[tag])
    await maintainer.post(
        f"/api/v1/scenarios/{parent['id']}/versions", json={"content": {"constraints": ["Court"]}}
    )
    await maintainer.post(
        f"/api/v1/scenarios/{parent['id']}/variants",
        json={"label": "v2", "overrides": {"constraints": []}, "tags": [tag]},
    )
    exported = await maintainer.get("/api/v1/scenarios/export", params={"tag": tag})
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("application/yaml")
    bundle = yaml.safe_load(exported.text)
    assert bundle["format"] == "forge.scenarios/v1"
    slugs = [s["slug"] for s in bundle["scenarios"]]
    assert slugs == [parent["slug"], f"{parent['slug']}_variant_v2"]
    assert len(bundle["scenarios"][0]["versions"]) == 2
    assert bundle["scenarios"][1]["parent_slug"] == parent["slug"]

    # Re-import as-is: nothing changes.
    same = await maintainer.post(
        "/api/v1/scenarios/import", content=exported.content, headers={"Content-Type": "application/yaml"}
    )
    assert same.status_code == 200, same.text
    assert len(same.json()["skipped"]) == 2 and not same.json()["created"]

    # Rename slugs → new scenarios (dry run first).
    suffix = uuid.uuid4().hex[:6]
    for entry in bundle["scenarios"]:
        entry["slug"] = f"{entry['slug']}_{suffix}"
        if entry["parent_slug"]:
            entry["parent_slug"] = f"{entry['parent_slug']}_{suffix}"
    dry = await maintainer.post("/api/v1/scenarios/import", json={"bundle": bundle, "dry_run": True})
    assert dry.status_code == 200, dry.text
    assert dry.json()["dry_run"] is True and len(dry.json()["created"]) == 2
    assert (await maintainer.get("/api/v1/scenarios", params={"q": suffix})).json()["total"] == 0

    real = await maintainer.post("/api/v1/scenarios/import", json=bundle)
    report = real.json()
    assert len(report["created"]) == 2 and report["errors"] == []
    assert report["created"][0]["versions"] == [1, 2]
    imported = (await maintainer.get("/api/v1/scenarios", params={"q": suffix})).json()["items"]
    child = next(s for s in imported if s["parent_scenario_id"])
    root = next(s for s in imported if not s["parent_scenario_id"])
    assert child["family_id"] == root["id"]

    json_export = await maintainer.get(
        "/api/v1/scenarios/export", params={"q": suffix, "format": "json", "versions": "latest"}
    )
    data = json.loads(json_export.text)
    assert all(len(s["versions"]) == 1 for s in data["scenarios"])


async def test_import_reports_entry_errors_and_multipart(client_as) -> None:
    editor = await client_as(Role.editor)
    good_slug = _slug("scenario_imp")
    bundle = {
        "format": "forge.scenarios/v1",
        "scenarios": [
            {"slug": good_slug, "name": "OK", "category": "analysis", "versions": [{"content": {"input": {"prompt": "x"}}}]},
            {"slug": _slug("scenario_bad"), "name": "KO", "category": "analysis", "versions": [{"content": {"input": {}}}]},
            {
                "slug": _slug("scenario_priv"), "name": "Privé", "category": "analysis", "visibility": "private",
                "versions": [{"content": {"input": {"prompt": "x"}}}],
            },
            {
                "slug": _slug("scenario_orphan"), "name": "Orphelin", "category": "analysis", "parent_slug": "inconnu_abc",
                "versions": [{"content": {"input": {"prompt": "x"}}}],
            },
        ],
    }  # fmt: skip
    response = await editor.post(
        "/api/v1/scenarios/import",
        files={
            "file": ("bundle.yaml", yaml.safe_dump(bundle, allow_unicode=True).encode(), "application/yaml")
        },
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert [c["slug"] for c in report["created"]] == [good_slug]
    assert len(report["errors"]) == 3
    messages = " ".join(e["message"] for e in report["errors"])
    assert "Scénario invalide" in messages and "mainteneurs" in messages and "parent" in messages
    bad_format = await editor.post("/api/v1/scenarios/import", json={"bundle": {"format": "x"}})
    assert bad_format.status_code == 422
    unsupported = await editor.post(
        "/api/v1/scenarios/import", content=b"x", headers={"Content-Type": "image/png"}
    )
    assert unsupported.status_code == 415
