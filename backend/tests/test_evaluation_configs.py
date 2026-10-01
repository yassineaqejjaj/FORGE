"""Evaluation configurations API: versions, validation, default flag, preview (no persistence)."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from forge.domain.enums import Role
from forge.infra.models import CompositeScore, EvaluationConfig, Judge
from forge.services import runs as run_service
from tests.conftest import run_jobs
from tests.factories import attach_trace, create_agent_version, create_run, create_scenario_version


async def _heuristic_id(db_session) -> str:
    judge = await db_session.scalar(
        select(Judge).where(Judge.key == "forge-heuristic", Judge.is_latest.is_(True))
    )
    return str(judge.id)


def _body(judge_id: str, **extra) -> dict:
    return {
        "key": f"cfg-{uuid.uuid4().hex[:8]}",
        "name": "Configuration test",
        "dimension_weights": {"quality": 0.6, "safety": 0.4},
        "judge_ids": [judge_id],
        "aggregation": {"method": "mean"},
        "gates": [
            {"id": "floor", "kind": "dimension", "target": "safety", "min": 0.5, "action": "cap", "cap": 40}
        ],
        "rules": [{"id": "pii", "type": "no_pii"}, {"id": "hidden", "type": "no_canary", "hidden": True}],
        **extra,
    }


async def test_create_version_conflict_and_default(db_session, client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    body = _body(await _heuristic_id(db_session))
    created = await maintainer.post("/api/v1/evaluation-configs", json=body)
    assert created.status_code == 201, created.text
    v1 = created.json()
    assert v1["version"] == 1 and v1["judges"][0]["key"] == "forge-heuristic"
    assert v1["rules"][1]["params"] == {}  # normalised RuleSpec JSON
    assert (await maintainer.post("/api/v1/evaluation-configs", json=body)).status_code == 409
    same = await maintainer.post(
        f"/api/v1/evaluation-configs/{v1['id']}/versions", json={"name": "Nouveau nom"}
    )
    assert same.status_code == 409
    v2 = await maintainer.post(
        f"/api/v1/evaluation-configs/{v1['id']}/versions",
        json={"dimension_weights": {"quality": 1.0}, "is_default": True},
    )
    assert v2.status_code == 201, v2.text
    assert v2.json()["version"] == 2 and v2.json()["is_default"] is True
    defaults = list(
        await db_session.scalars(select(EvaluationConfig).where(EvaluationConfig.is_default.is_(True)))
    )
    assert [c.key for c in defaults] == [body["key"]]
    # Restore the bootstrap default for the other tests of the session.
    restore = await maintainer.post(
        f"/api/v1/evaluation-configs/{defaults[0].id}/versions",
        json={"is_default": False, "pass_threshold": 71},
    )
    assert restore.status_code == 201
    forge_default = await db_session.scalar(
        select(EvaluationConfig).where(
            EvaluationConfig.key == "forge-default", EvaluationConfig.is_latest.is_(True)
        )
    )
    forge_default.is_default = True
    await db_session.commit()
    viewer = await client_as(Role.viewer)
    seen = (await viewer.get(f"/api/v1/evaluation-configs/{v1['id']}")).json()
    assert seen["rules"][1]["description"] == "Règle masquée"  # hidden rule masked for non-maintainers
    listing = (await viewer.get("/api/v1/evaluation-configs", params={"key": body["key"]})).json()
    assert listing["total"] == 3


async def test_validation(db_session, client_as) -> None:
    maintainer = await client_as(Role.maintainer)
    judge_id = await _heuristic_id(db_session)
    cases = [
        {"dimension_weights": {"quality": 0, "safety": 0}},
        {"dimension_weights": {"robustness": 1}},
        {"dimension_weights": {"quality": -1, "safety": 1}},
        {"dimension_weights": {"vibes": 1}},
        {"judge_ids": [str(uuid.uuid4())]},
        {"aggregation": {"method": "custom", "expression": "__import__('os')"}},
        {"aggregation": {"method": "nope"}},
        {"gates": [{"id": "g", "kind": "dimension", "target": "safety", "min": 3}]},
        {"gates": [{"id": "g", "kind": "error", "target": "NOT_A_TYPE"}]},
        {"rules": [{"id": "r", "type": "regex_match", "params": {"pattern": "("}}]},
        {"rules": [{"id": "r", "type": "contains", "params": {"keywords": ["x"]}, "error_type": "UNKNOWN"}]},
        {"criteria": ["no.such"]},
        {"normalization": {"cost_target": 1, "cost_max": 0.5}},
    ]
    for extra in cases:
        response = await maintainer.post("/api/v1/evaluation-configs", json=_body(judge_id, **extra))
        assert response.status_code == 422, (extra, response.text)
    ok = await maintainer.post(
        "/api/v1/evaluation-configs",
        json=_body(
            judge_id,
            aggregation={
                "method": "custom",
                "expression": "min(scores) if len(scores) > 1 else mean(scores)",
            },
        ),
    )
    assert ok.status_code == 201
    editor = await client_as(Role.editor)
    assert (await editor.post("/api/v1/evaluation-configs", json=_body(judge_id))).status_code == 403


async def test_preview_recomputes_without_persisting(db_session, client_as) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(
        db_session, rules=[{"id": "pii", "type": "no_pii", "severity": "high"}]
    )
    run = await create_run(db_session, sv, av)
    await attach_trace(db_session, run, output_text="# Objectifs\nPRD export CSV, contact jean@example.com")
    await run_service.mark_evaluating(db_session, run)
    await db_session.commit()
    await run_jobs()
    await db_session.refresh(run)
    before_rows = len(
        list(await db_session.scalars(select(CompositeScore).where(CompositeScore.run_id == run.id)))
    )
    viewer = await client_as(Role.viewer)
    config_id = run.evaluation_config_id
    response = await viewer.post(
        f"/api/v1/evaluation-configs/{config_id}/preview",
        json={
            "run_ids": [str(run.id), str(uuid.uuid4())],
            "overrides": {"gates": [], "dimension_weights": {"quality": 1}},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    (item,) = data["items"]
    assert item["before"] == run.composite_score and item["gate_failed_before"] is True  # DATA_LEAK gate
    assert item["gate_failed_after"] is False and item["after"] > 0
    assert any(s["reason"] == "run introuvable" for s in data["skipped"])
    assert data["notes"]
    after_rows = len(
        list(await db_session.scalars(select(CompositeScore).where(CompositeScore.run_id == run.id)))
    )
    assert after_rows == before_rows
    await db_session.refresh(run)
    assert run.composite_score == item["before"]
    bad = await viewer.post(f"/api/v1/evaluation-configs/{config_id}/preview", json={})
    assert bad.status_code == 422
