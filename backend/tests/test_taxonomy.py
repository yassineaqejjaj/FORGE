"""Criteria catalog and error taxonomy: list, custom creation (maintainer), built-ins protected."""

from __future__ import annotations

import uuid

from forge.domain.enums import Role


async def test_list_criteria_and_error_types(client_as) -> None:
    viewer = await client_as(Role.viewer)
    criteria = (await viewer.get("/api/v1/criteria")).json()
    accuracy = next(c for c in criteria if c["key"] == "quality.accuracy")
    assert accuracy["builtin"] and accuracy["dimension_label"] == "Qualité" and accuracy["judged"]
    safety = (await viewer.get("/api/v1/criteria", params={"dimension": "safety"})).json()
    assert safety and all(c["dimension"] == "safety" for c in safety)
    errors = (await viewer.get("/api/v1/error-types")).json()
    assert any(e["code"] == "DATA_LEAK" and e["builtin"] for e in errors)


async def test_custom_criterion(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    key = f"ux.tone_{uuid.uuid4().hex[:6]}"
    created = await maintainer.post(
        "/api/v1/criteria",
        json={"key": key, "name": "Ton", "question": "Le ton est-il adapté ?", "scale_max": 10},
    )
    assert created.status_code == 201, created.text
    assert created.json()["dimension"] == "ux" and created.json()["builtin"] is False
    assert (await maintainer.post("/api/v1/criteria", json={"key": key, "name": "x"})).status_code == 409
    builtin = await maintainer.post("/api/v1/criteria", json={"key": "quality.accuracy", "name": "x"})
    assert builtin.status_code == 409 and "intégré" in builtin.json()["detail"]
    for bad in ("tone", "style.tone", "ux.Tone", "ux."):
        assert (
            await maintainer.post("/api/v1/criteria", json={"key": bad, "name": "x"})
        ).status_code == 422, bad
    scale = await maintainer.post(
        "/api/v1/criteria", json={"key": "ux.scale_bad", "name": "x", "scale_min": 5, "scale_max": 1}
    )
    assert scale.status_code == 422
    editor = await client_as(Role.editor)
    assert (await editor.post("/api/v1/criteria", json={"key": "ux.other", "name": "x"})).status_code == 403


async def test_custom_error_type(client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    code = f"WRONG_UNIT_{uuid.uuid4().hex[:6].upper()}"
    created = await maintainer.post(
        "/api/v1/error-types",
        json={"code": code, "label": "Mauvaise unité", "default_severity": "high", "dimension": "quality"},
    )
    assert created.status_code == 201, created.text
    assert (
        await maintainer.post("/api/v1/error-types", json={"code": code, "label": "x"})
    ).status_code == 409
    assert (
        await maintainer.post("/api/v1/error-types", json={"code": "HALLUCINATION", "label": "x"})
    ).status_code == 409
    assert (
        await maintainer.post("/api/v1/error-types", json={"code": "wrong_case", "label": "x"})
    ).status_code == 422
    # The new code can now be used by scenario rules.
    editor = await client_as(Role.editor)
    scenario = await editor.post(
        "/api/v1/scenarios",
        json={
            "name": "Unités",
            "category": "analysis",
            "content": {
                "input": {"prompt": "Convertis"},
                "rules": [{"type": "json_valid", "error_type": code}],
            },
        },
    )
    assert scenario.status_code == 201, scenario.text
