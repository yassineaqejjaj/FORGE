"""Promotion policy (FORGE_PROMOTION_POLICY): calibrated judges, contamination, regression cases, gate."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select, update

from forge.config import settings
from forge.domain.enums import DatasetKind, Dimension, EvaluatorKind, ExperimentArm, ProviderKind, Role
from forge.infra.db import get_sessionmaker
from forge.infra.models import (
    AgentVersion,
    AuditEvent,
    Dataset,
    DatasetItem,
    Evaluation,
    EvaluationRun,
    Experiment,
    ExperimentScenario,
    Judge,
    Scenario,
)
from forge.services import credentials as credential_service
from forge.services import evaluation_configs as config_service
from tests.analytics_fixtures import complete_runs, make_catalog
from tests.factories import (
    complete_with_scores,
    create_agent_version,
    create_run,
    create_scenario_version,
)
from tests.test_experiments import _winning_scorer

CRITERION = "quality.synthetic"


@pytest.fixture
def strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    monkeypatch.setattr(settings, "calibration_min_kappa", 0.6)


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


async def _config_with_judge(*, agree: bool = True, on_gold: bool = True, n_runs: int = 12) -> uuid.UUID:
    """An evaluation config pinning one judge whose gold-set agreement with humans is controlled."""
    async with get_sessionmaker()() as session:
        judge = Judge(
            key=f"judge-{uuid.uuid4().hex[:6]}",
            version=1,
            name="Juge",
            provider="heuristic",
            model="heuristic",
            system_prompt="Évalue.",
            content_hash=f"sha256:{uuid.uuid4().hex}",
        )
        session.add(judge)
        sv = await create_scenario_version(session)
        av = await create_agent_version(session)
        gold = Dataset(slug=f"gold-{uuid.uuid4().hex[:6]}", name="Gold", kind=DatasetKind.gold)
        session.add(gold)
        await session.flush()
        for i in range(n_runs):
            run = await create_run(session, sv, av, repetition=i)
            value = i / (n_runs - 1)
            await complete_with_scores(session, run, composite=value * 100)
            session.add(
                _evaluation(run.id, kind=EvaluatorKind.human, key="human:t", score=value, round_=None)
            )
            session.add(
                _evaluation(
                    run.id,
                    kind=EvaluatorKind.llm_judge,
                    key=f"{judge.key}@v1",
                    score=value if agree else 1 - value,
                    round_=1,
                    judge_id=judge.id,
                )
            )
            if on_gold:
                session.add(DatasetItem(dataset_id=gold.id, key=f"item-{i}", run_id=run.id))
        config = await config_service.create_config(
            session,
            key=f"cfg-{uuid.uuid4().hex[:6]}",
            name="Config promotion",
            dimension_weights={"quality": 1.0, "cost": 0.0},
            judge_ids=[str(judge.id)],
        )
        await session.commit()
        return config.id


async def _create(client, v1, v2, scenario_ids, config_id, **extra):
    return await client.post(
        "/api/v1/experiments",
        json={
            "baseline_version_id": str(v1),
            "candidate_version_id": str(v2),
            "scenario_ids": [str(s) for s in scenario_ids],
            "evaluation_config_id": str(config_id),
            **extra,
        },
    )


async def test_strict_policy_refuses_experiments_with_an_uncalibrated_judge(client_as, strict) -> None:
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=2)
    editor = await client_as(Role.editor)
    uncalibrated = await _config_with_judge(agree=False)  # harsh judge: κ < 0.6 on the gold set
    refused = await _create(editor, v1, v2, scenario_ids, uncalibrated)
    assert refused.status_code == 422 and "non calibré" in refused.json()["detail"]
    no_gold = await _create(editor, v1, v2, scenario_ids, await _config_with_judge(on_gold=False))
    assert no_gold.status_code == 422 and "aucune mesure" in no_gold.json()["detail"]  # not a gold set
    too_few = await _create(editor, v1, v2, scenario_ids, await _config_with_judge(n_runs=6))
    assert too_few.status_code == 422 and "n=6" in too_few.json()["detail"]
    calibrated = await _create(editor, v1, v2, scenario_ids, await _config_with_judge(agree=True))
    assert calibrated.status_code == 201, calibrated.text


async def test_calibration_threshold_is_configurable(client_as, strict, monkeypatch) -> None:
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=2)
    editor = await client_as(Role.editor)
    config_id = await _config_with_judge(agree=True)
    monkeypatch.setattr(settings, "calibration_min_kappa", 1.0)
    # Perfect agreement still reaches κ = 1: the threshold is inclusive.
    assert (await _create(editor, v1, v2, scenario_ids, config_id)).status_code == 201
    harsh = await _config_with_judge(agree=False)
    monkeypatch.setattr(settings, "calibration_min_kappa", 0.0)
    # A negative-agreement judge stays refused even with a null κ threshold (agreement ≥ 0.7 required).
    assert (await _create(editor, v1, v2, scenario_ids, harsh)).status_code == 422


async def test_warn_policy_creates_and_reports_the_findings(client_as, monkeypatch) -> None:
    monkeypatch.setattr(settings, "promotion_policy", "warn")
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=2)
    editor = await client_as(Role.editor)
    created = await _create(editor, v1, v2, scenario_ids, await _config_with_judge(agree=False))
    assert created.status_code == 201, created.text
    async with get_sessionmaker()() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "experiment.create", AuditEvent.target_id == created.json()["id"]
            )
        )
    assert any("non calibré" in w for w in audit.details["warnings"])


async def test_contaminated_versions_block_experiments_under_the_strict_policy(client_as, strict) -> None:
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=2)
    editor = await client_as(Role.editor)
    config_id = await _config_with_judge()
    async with get_sessionmaker()() as session:
        await session.execute(
            update(AgentVersion).where(AgentVersion.id == v2).values(contamination=[{"kind": "canary"}])
        )
        await session.commit()
    refused = await _create(editor, v1, v2, scenario_ids, config_id)
    assert refused.status_code == 422 and "contamination" in refused.json()["detail"]


async def _winning_experiment(client, config_id, monkeypatch, *, n_scenarios: int = 8):
    """A shippable experiment created under ``warn`` (so any config can be used), judged afterwards."""
    monkeypatch.setattr(settings, "promotion_policy", "warn")
    scenario_ids, (v1, v2) = await make_catalog(n_scenarios=n_scenarios)
    created = (
        await _create(client, v1, v2, scenario_ids, config_id, repetitions=2, hypothesis="Citer")
    ).json()
    await complete_runs(_winning_scorer(scenario_ids, 9.0), experiment_id=uuid.UUID(created["id"]))
    return created, scenario_ids, v1, v2


async def test_gate_blocks_on_uncalibrated_judges_in_strict_and_only_warns_otherwise(
    client_as, monkeypatch
) -> None:
    editor = await client_as(Role.editor)
    created, *_ = await _winning_experiment(editor, await _config_with_judge(agree=False), monkeypatch)
    url = f"/api/v1/experiments/{created['id']}/gate"
    warn = (await editor.get(url)).json()
    assert warn["passed"] is True and any(
        "Avertissement" in r and "non calibré" in r for r in warn["reasons"]
    )
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    blocked = (await editor.get(url, params={"strict": False})).json()
    assert blocked["passed"] is False and blocked["recommendation"] == "ship" and blocked["strict"] is True
    assert any("Promotion bloquée" in r and "non calibré" in r for r in blocked["reasons"])
    good, *_ = await _winning_experiment(editor, await _config_with_judge(agree=True), monkeypatch)
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    assert (await editor.get(f"/api/v1/experiments/{good['id']}/gate")).json()["passed"] is True


async def test_inconclusive_does_not_pass_the_default_gate_under_the_strict_policy(
    client_as, monkeypatch
) -> None:
    editor = await client_as(Role.editor)
    created, *_ = await _winning_experiment(editor, await _config_with_judge(), monkeypatch)
    async with get_sessionmaker()() as session:
        experiment = await session.get(Experiment, uuid.UUID(created["id"]))
        comparison = json.loads(json.dumps(experiment.comparison))
        comparison["recommendation"]["recommendation"] = "inconclusive"
        experiment.comparison, experiment.recommendation = comparison, "inconclusive"
        await session.commit()
    url = f"/api/v1/experiments/{created['id']}/gate"
    assert (await editor.get(url)).json()["passed"] is True  # warn: historical behaviour
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    strict_gate = (await editor.get(url)).json()
    assert strict_gate["passed"] is False and strict_gate["strict"] is True


async def test_regression_cases_must_be_replayed_under_the_strict_policy(client_as, monkeypatch) -> None:
    editor = await client_as(Role.editor)
    created, *_ = await _winning_experiment(editor, await _config_with_judge(), monkeypatch)
    async with get_sessionmaker()() as session:
        run = await session.scalar(
            select(EvaluationRun).where(
                EvaluationRun.experiment_id == uuid.UUID(created["id"]),
                EvaluationRun.arm == ExperimentArm.candidate,
            )
        )
        case = await create_scenario_version(session, name="Cas de régression")
        scenario = await session.get(Scenario, case.scenario_id)
        scenario.tags = ["regression", f"from-run:{run.id}"]
        await session.commit()
    url = f"/api/v1/experiments/{created['id']}/gate"
    assert (await editor.get(url)).json()["passed"] is True  # warn: noted, not blocking
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    blocked = (await editor.get(url)).json()
    assert blocked["passed"] is False and any("cas de régression" in r for r in blocked["reasons"])
    async with get_sessionmaker()() as session:  # the case is replayed once it is part of the experiment
        session.add(
            ExperimentScenario(
                experiment_id=uuid.UUID(created["id"]),
                scenario_version_id=case.id,
                scenario_id=case.scenario_id,
                position=99,
            )
        )
        await session.commit()
    assert (await editor.get(url)).json()["passed"] is True


async def _orbit_credential() -> uuid.UUID:
    async with get_sessionmaker()() as session:
        credential = await credential_service.create_credential(
            session,
            name=f"orbit-{uuid.uuid4().hex[:6]}",
            kind=ProviderKind.orbit,
            secret="orbit-key-9",
            base_url="https://orbit.example",
        )
        await session.commit()
        return credential.id


@respx.mock
async def test_publication_is_blocked_by_contamination_or_uncalibrated_judges(client_as, monkeypatch) -> None:
    editor = await client_as(Role.editor)
    credential = await _orbit_credential()
    body = {"orbit_project": "atlas", "credential_id": str(credential)}
    route = respx.post("https://orbit.example/api/v1/projects/atlas/learnings").mock(
        return_value=httpx.Response(201, json={"id": "5b5b5b5b-0000-4000-8000-000000000003"})
    )
    # Uncalibrated judge: refused under strict, published (with the finding audited) under warn.
    weak, *_ = await _winning_experiment(editor, await _config_with_judge(agree=False), monkeypatch)
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    refused = await editor.post(f"/api/v1/experiments/{weak['id']}/publish-learning", json=body)
    assert refused.status_code == 422 and "politique de promotion" in refused.json()["detail"]
    assert route.call_count == 0
    # Calibrated judge but a contaminated candidate: still refused.
    good, _, _, v2 = await _winning_experiment(editor, await _config_with_judge(), monkeypatch)
    async with get_sessionmaker()() as session:
        await session.execute(
            update(AgentVersion).where(AgentVersion.id == v2).values(contamination=[{"kind": "canary"}])
        )
        await session.commit()
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    contaminated = await editor.post(f"/api/v1/experiments/{good['id']}/publish-learning", json=body)
    assert contaminated.status_code == 422 and "contamination" in contaminated.json()["detail"]
    assert route.call_count == 0
    monkeypatch.setattr(settings, "promotion_policy", "warn")
    published = await editor.post(f"/api/v1/experiments/{good['id']}/publish-learning", json=body)
    assert published.status_code == 201, published.text
    async with get_sessionmaker()() as session:
        audit = await session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "experiment.publish_learning", AuditEvent.target_id == good["id"]
            )
        )
    assert any("contamination" in w for w in audit.details["promotion_warnings"])


async def test_a_calibrated_clean_experiment_is_published_under_the_strict_policy(
    client_as, monkeypatch
) -> None:
    editor = await client_as(Role.editor)
    credential = await _orbit_credential()
    good, *_ = await _winning_experiment(editor, await _config_with_judge(), monkeypatch)
    monkeypatch.setattr(settings, "promotion_policy", "strict")
    with respx.mock(assert_all_called=False) as router:
        router.post("https://orbit.example/api/v1/projects/atlas/learnings").mock(
            return_value=httpx.Response(201, json={"id": "5b5b5b5b-0000-4000-8000-000000000004"})
        )
        response = await editor.post(
            f"/api/v1/experiments/{good['id']}/publish-learning",
            json={"orbit_project": "atlas", "credential_id": str(credential)},
        )
    assert response.status_code == 201, response.text
