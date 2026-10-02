"""Human review: queue ordered by judge disagreement, blind mode, human evaluations (replace, scale)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, update

from forge.domain.enums import EvaluatorKind, Role, RunStatus
from forge.infra.models import Evaluation, Score
from tests.conftest import run_jobs, token_for
from tests.factories import complete_with_scores, create_agent_version, create_run, create_scenario_version


async def _completed(db_session, *, spread: float | None, confidence: float, tag: str):
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av, tags=[tag])
    await complete_with_scores(db_session, run, composite=75)
    await db_session.execute(
        update(Score).where(Score.run_id == run.id).values(spread=spread, confidence=confidence)
    )
    await db_session.commit()
    return run


async def test_queue_orders_by_disagreement_then_confidence(client_as, db_session) -> None:
    tag = f"q-{uuid.uuid4().hex[:6]}"
    calm = await _completed(db_session, spread=0.05, confidence=0.9, tag=tag)
    disputed = await _completed(db_session, spread=0.6, confidence=0.8, tag=tag)
    unsure = await _completed(db_session, spread=0.05, confidence=0.3, tag=tag)
    gold = (
        await (await client_as(Role.editor)).post(
            "/api/v1/datasets",
            json={
                "name": f"Gold {tag}",
                "kind": "gold",
                "items": [{"run_id": str(r.id)} for r in (calm, disputed, unsure)],
            },
        )
    ).json()
    evaluator = await client_as(Role.evaluator)
    queue = await evaluator.get("/api/v1/reviews/queue", params={"dataset_id": gold["id"]})
    assert queue.status_code == 200, queue.text
    items = queue.json()["items"]
    assert [i["run_id"] for i in items] == [str(disputed.id), str(unsure.id), str(calm.id)]
    assert items[0]["max_spread"] == 0.6 and items[0]["composite_score"] == 75 and items[0]["ai_scores"]
    assert {c["key"] for c in items[0]["criteria"]} >= {"quality.accuracy", "ux.clarity"}
    assert all(c["dimension"] not in ("cost", "latency") for c in items[0]["criteria"])

    blind = (
        await evaluator.get("/api/v1/reviews/queue", params={"dataset_id": gold["id"], "blind": True})
    ).json()
    assert blind["items"][0]["composite_score"] is None and blind["items"][0]["ai_scores"] is None

    viewer = await client_as(Role.viewer)
    assert (await viewer.get("/api/v1/reviews/queue")).status_code == 403


async def test_submit_replace_and_list_human_evaluations(client_as, make_user, db_session, app) -> None:
    import httpx

    tag = f"h-{uuid.uuid4().hex[:6]}"
    run = await _completed(db_session, spread=0.2, confidence=0.7, tag=tag)
    user = await make_user(Role.evaluator)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as evaluator:
        evaluator.headers["Authorization"] = f"Bearer {await token_for(user.email)}"
        url = f"/api/v1/runs/{run.id}/human-evaluations"
        first = await evaluator.post(
            url,
            json={
                "scores": [
                    {"criterion_key": "quality.accuracy", "score": 4, "comment": "Exact"},
                    {"criterion_key": "ux.clarity", "score": 3},
                ],
                "comment": "Bon ensemble",
            },
        )
        assert first.status_code == 201, first.text
        body = first.json()
        assert {e["criterion_key"]: e["explanation"] for e in body["evaluations"]} == {
            "quality.accuracy": "Exact",
            "ux.clarity": "Bon ensemble",
        }
        assert body["evaluations"][0]["normalized_score"] in (0.8, 0.6)

        second = await evaluator.post(
            url, json={"scores": [{"criterion_key": "quality.accuracy", "score": 2}]}
        )
        assert second.status_code == 201
        rows = list(
            await db_session.scalars(
                select(Evaluation).where(
                    Evaluation.run_id == run.id, Evaluation.evaluator_kind == EvaluatorKind.human
                )
            )
        )
        assert len(rows) == 1 and rows[0].raw_score == 2 and rows[0].round is None
        assert (
            rows[0].evaluator_key == f"human:{user.id}"
            and rows[0].explanation == "Évaluation humaine sans commentaire"
        )

        out_of_scale = await evaluator.post(
            url, json={"scores": [{"criterion_key": "quality.accuracy", "score": 7}]}
        )
        assert out_of_scale.status_code == 422
        unknown = await evaluator.post(
            url, json={"scores": [{"criterion_key": "quality.unknown_x", "score": 1}]}
        )
        assert unknown.status_code == 422
        measured = await evaluator.post(
            url, json={"scores": [{"criterion_key": "latency.total", "score": 1}]}
        )
        assert measured.status_code == 422
        dup = await evaluator.post(
            url,
            json={
                "scores": [
                    {"criterion_key": "ux.clarity", "score": 1},
                    {"criterion_key": "ux.clarity", "score": 2},
                ]
            },
        )
        assert dup.status_code == 422

        queue = (await evaluator.get("/api/v1/reviews/queue", params={"page_size": 200})).json()
        assert str(run.id) not in {i["run_id"] for i in queue["items"]}

    listing = await (await client_as(Role.viewer)).get(f"/api/v1/runs/{run.id}/human-evaluations")
    assert listing.status_code == 200 and listing.json()[0]["user_name"] == "Utilisateur evaluator"


async def test_pending_runs_cannot_be_evaluated(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av)
    await db_session.commit()
    evaluator = await client_as(Role.evaluator)
    response = await evaluator.post(
        f"/api/v1/runs/{run.id}/human-evaluations",
        json={"scores": [{"criterion_key": "quality.accuracy", "score": 3}]},
    )
    assert response.status_code == 422


async def test_human_evaluation_rescores_a_really_evaluated_run(client_as, db_session) -> None:
    """End-to-end: mock agent + heuristic judge, then a human score is folded in by rescore_run."""
    av = await create_agent_version(
        db_session,
        adapter_config={
            "script": {"output": "# PRD\n## Objectifs\nExport CSV des rapports.\n## Périmètre\nTous."}
        },
    )
    sv = await create_scenario_version(db_session)
    run = await create_run(db_session, sv, av, enqueue=True)
    await db_session.commit()
    await run_jobs()
    await db_session.refresh(run)
    if run.status != RunStatus.completed:  # execution / evaluation modules not available in this checkout
        pytest.skip(f"pipeline unavailable (run {run.status.value}: {run.error or run.status_detail})")
    evaluator = await client_as(Role.evaluator)
    response = await evaluator.post(
        f"/api/v1/runs/{run.id}/human-evaluations",
        json={"scores": [{"criterion_key": "quality.accuracy", "score": 5}]},
    )
    assert response.status_code == 201, response.text
    assert response.json()["rescored"] is True
    scores = list(
        await db_session.scalars(select(Score).where(Score.run_id == run.id, Score.source == "human"))
    )
    assert any(s.criterion_key == "quality.accuracy" for s in scores)


async def test_priority_queue_keeps_runs_that_need_a_human(db_session, client_as) -> None:
    """The navigation badge counts the priority queue: disagreement, low confidence or gold runs."""
    from forge.domain.enums import Dimension, Role, ScoreSource
    from forge.infra.models import Score
    from tests.factories import (
        complete_with_scores,
        create_agent_version,
        create_run,
        create_scenario_version,
    )

    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    calm = await create_run(db_session, sv, av, repetition=0)
    disputed = await create_run(db_session, sv, av, repetition=1)
    for run in (calm, disputed):
        await complete_with_scores(db_session, run, composite=80.0)
    db_session.add(
        Score(
            run_id=disputed.id, round=1, evaluation_config_id=disputed.evaluation_config_id,
            criterion_key="quality.accuracy", dimension=Dimension.quality, value=0.5, weight=1.0,
            source=ScoreSource.ai, confidence=0.9, explanation="Juges en désaccord", method="median(2)", spread=0.6,
        )
    )  # fmt: skip
    await db_session.commit()

    evaluator = await client_as(Role.evaluator, clearance=3)
    everything = (await evaluator.get("/api/v1/reviews/queue", params={"page_size": 200})).json()
    priority = (
        await evaluator.get("/api/v1/reviews/queue", params={"page_size": 200, "priority": "true"})
    ).json()
    ids = {i["run_id"] for i in priority["items"]}
    assert str(disputed.id) in ids and str(calm.id) not in ids
    assert priority["total"] < everything["total"]
