"""Calibration API: pairs from human evaluations vs aggregated / individual AI scores (§9.4)."""

from __future__ import annotations

import uuid

import pytest

from forge.domain.enums import DatasetKind, Dimension, EvaluatorKind, Role
from forge.infra.db import get_sessionmaker
from forge.infra.models import Dataset, DatasetItem, Evaluation, Judge, Scenario
from tests.analytics_fixtures import custom_plans
from tests.factories import complete_with_scores, create_agent_version, create_run, create_scenario_version

pytestmark = pytest.mark.usefixtures("custom_plans")
_FIXTURES = (custom_plans,)

CRITERION = "quality.synthetic"


def _evaluation(run_id, *, kind, key, score, round_, judge_id=None) -> Evaluation:
    return Evaluation(
        run_id=run_id,
        round=round_,
        evaluator_kind=kind,
        evaluator_key=key,
        criterion_key=CRITERION,
        dimension=Dimension.quality,
        raw_score=score * 5,
        scale_min=0.0,
        scale_max=5.0,
        normalized_score=score,
        confidence=0.8,
        explanation="Évaluation de test",
        judge_id=judge_id,
    )


async def _setup(n_runs: int = 12, classification: int = 1) -> dict:
    async with get_sessionmaker()() as session:
        judge = Judge(
            key=f"judge-{uuid.uuid4().hex[:6]}", version=1, name="Juge test", provider="heuristic",
            model="heuristic", system_prompt="Évalue.", content_hash=f"sha256:{uuid.uuid4().hex}",
        )  # fmt: skip
        session.add(judge)
        av = await create_agent_version(session)
        sv = await create_scenario_version(session)
        scenario = await session.get(Scenario, sv.scenario_id)
        scenario.classification = classification
        dataset = Dataset(slug=f"gold-{uuid.uuid4().hex[:6]}", name="Gold test", kind=DatasetKind.gold)
        context = Dataset(slug=f"ctx-{uuid.uuid4().hex[:6]}", name="Contexte", kind=DatasetKind.context)
        session.add_all([dataset, context])
        await session.flush()
        run_ids = []
        for i in range(n_runs):
            run = await create_run(session, sv, av, repetition=i)
            value = i / (n_runs - 1)
            await complete_with_scores(
                session, run, composite=value * 100
            )  # ai score quality.synthetic = value
            session.add(
                _evaluation(
                    run.id,
                    kind=EvaluatorKind.human,
                    key="human:test",
                    score=min(1.0, value + 0.05),
                    round_=None,
                )
            )
            # The judge is harsh: it disagrees with humans on every run.
            session.add(
                _evaluation(
                    run.id,
                    kind=EvaluatorKind.llm_judge,
                    key=f"{judge.key}@v1",
                    score=1 - value,
                    round_=1,
                    judge_id=judge.id,
                )
            )
            if i < 4:
                session.add(DatasetItem(dataset_id=dataset.id, key=f"item-{i}", run_id=run.id))
            run_ids.append(run.id)
        await session.commit()
        return {
            "judge": judge.id,
            "judge_key": f"{judge.key}@v1",
            "dataset": dataset.id,
            "context": context.id,
        }


async def test_calibration_report(client_as) -> None:
    ids = await _setup()
    viewer = await client_as(Role.viewer)
    response = await viewer.get("/api/v1/calibration", params={"criterion_key": CRITERION})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["overall"]["key"] == "aggregate" and data["overall"]["n"] >= 12
    assert data["overall"]["status"] == "calibrated"
    judge = next(j for j in data["by_judge"] if j["key"] == ids["judge_key"])
    assert judge["n"] == 12 and judge["status"] == "uncalibrated" and judge["spearman"] == pytest.approx(-1.0)
    assert data["thresholds"]["min_pairs"] == 10
    assert data["pairs"] and {"run_id", "ai", "human", "judge_key"} <= set(data["pairs"][0])

    only_judge = (await viewer.get("/api/v1/calibration", params={"judge_id": str(ids["judge"])})).json()
    assert only_judge["filters"]["judge"] == ids["judge_key"]
    assert [j["key"] for j in only_judge["by_judge"]] == [ids["judge_key"]]
    assert only_judge["overall"]["judge_key"] == ids["judge_key"]

    gold = (await viewer.get("/api/v1/calibration", params={"dataset_id": str(ids["dataset"])})).json()
    assert gold["n_runs"] == 4 and gold["overall"]["status"] == "insufficient_data"
    assert gold["filters"]["dataset"] == "Gold test"

    not_gold = await viewer.get("/api/v1/calibration", params={"dataset_id": str(ids["context"])})
    assert not_gold.status_code == 422
    assert (
        await viewer.get("/api/v1/calibration", params={"judge_id": str(uuid.uuid4())})
    ).status_code == 404


async def test_calibration_respects_clearance(client_as) -> None:
    await _setup(n_runs=3, classification=3)
    low = await client_as(Role.viewer, clearance=0)
    data = (await low.get("/api/v1/calibration", params={"criterion_key": CRITERION})).json()
    assert data["n_runs"] == 0 and data["overall"]["n"] == 0
