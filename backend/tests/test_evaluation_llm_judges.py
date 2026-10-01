"""Evaluation with LLM judges (respx): parallel judges, aggregation, cost, judge cache, failures."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select, update

from forge.domain.enums import EvaluatorKind, ProviderKind, RunStatus, ScoreSource
from forge.infra.llm import base as llm_base
from forge.infra.models import AuditEvent, Evaluation, Judge, JudgeCacheEntry, Score
from forge.services import credentials as credential_service
from forge.services import evaluation_configs as config_service
from forge.services import judges as judge_service
from forge.services import runs as run_service
from tests.conftest import run_jobs
from tests.factories import attach_trace, create_agent_version, create_run, create_scenario_version

LLM_URL = "https://llm.test/v1/chat/completions"
CRITERIA = ["quality.accuracy", "quality.completeness"]


@pytest.fixture(autouse=True)
def _instant_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(llm_base, "sleep", instant)


@pytest.fixture(autouse=True)
async def _disable_llm_judges_afterwards(db_session):
    """LLM judges created here must not leak into other suites sharing the database (``/meta``)."""
    yield
    await db_session.rollback()
    await db_session.execute(
        update(Judge).where(Judge.key.like("judge-%"), Judge.provider != "heuristic").values(enabled=False)
    )
    await db_session.commit()


def completion(scores: dict[str, float]) -> httpx.Response:
    content = json.dumps(
        {
            "criteria": [
                {"key": k, "score": v, "justification": f"Analyse de {k}.", "confidence": 0.9,
                 "errors": [{"type": "HALLUCINATION", "severity": "high", "description": "Chiffre inventé"}] if v < 2 else []}
                for k, v in scores.items()
            ]
        }
    )  # fmt: skip
    return httpx.Response(
        200,
        json={
            "model": "gpt-4.1-mini",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 2000, "completion_tokens": 300},
        },
    )


async def _setup(db_session, *, judges: int = 1, aggregation: str = "mean"):
    suffix = uuid.uuid4().hex[:6]
    credential = await credential_service.create_credential(
        db_session,
        name=f"llm-{suffix}",
        kind=ProviderKind.openai,
        secret="sk-test",
        base_url="https://llm.test/v1",
    )
    created = []
    for index in range(judges):
        created.append(
            await judge_service.create_judge(
                db_session, key=f"judge-{suffix}-{index}", name=f"Juge {index}", provider="openai",
                model="gpt-4.1-mini", criteria=CRITERIA, credential_id=str(credential.id),
            )
        )  # fmt: skip
    config = await config_service.create_config(
        db_session, key=f"cfg-{suffix}", name="Config LLM",
        dimension_weights={"quality": 1.0, "cost": 0.0},
        judge_ids=[str(j.id) for j in created], aggregation={"method": aggregation},
    )  # fmt: skip
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session, criteria=[{"key": k} for k in CRITERIA])
    return config, av, sv, created


async def _run(db_session, config, av, sv, output: str = "Un PRD complet."):
    run = await create_run(db_session, sv, av, config=config)
    await attach_trace(db_session, run, output_text=output, events=[])
    await run_service.mark_evaluating(db_session, run)
    await db_session.commit()
    return run


@respx.mock
async def test_two_judges_aggregated_with_cost(db_session) -> None:
    config, av, sv, judges = await _setup(db_session, judges=2)
    respx.post(LLM_URL).mock(
        side_effect=[completion({"quality.accuracy": 4, "quality.completeness": 5}),
                     completion({"quality.accuracy": 2, "quality.completeness": 5})]
    )  # fmt: skip
    run = await _run(db_session, config, av, sv)
    await run_jobs()
    await db_session.refresh(run)
    assert run.status == RunStatus.completed, run.status_detail
    judge_rows = list(
        await db_session.scalars(
            select(Evaluation).where(
                Evaluation.run_id == run.id, Evaluation.evaluator_kind == EvaluatorKind.llm_judge
            )
        )
    )
    assert len(judge_rows) == 4  # every individual verdict kept
    assert all(r.cost and r.cost > 0 for r in judge_rows)  # gpt-4.1-mini is priced
    accuracy = await db_session.scalar(
        select(Score).where(
            Score.run_id == run.id, Score.criterion_key == "quality.accuracy", Score.source == ScoreSource.ai
        )
    )
    assert accuracy.value == pytest.approx(0.6) and accuracy.n_evaluations == 2
    assert accuracy.spread == pytest.approx(0.4) and accuracy.method == "mean(2)"
    assert len(accuracy.evaluation_ids) == 2
    audit = await db_session.scalar(
        select(AuditEvent).where(AuditEvent.action == "run.evaluate", AuditEvent.target_id == str(run.id))
    )
    assert {j["key"] for j in audit.details["judges"]} == {j.key for j in judges}
    assert all(j["prompt_hash"].startswith("sha256:") for j in audit.details["judges"])


@respx.mock
async def test_judge_cache_reused_for_identical_output(db_session) -> None:
    config, av, sv, _ = await _setup(db_session)
    route = respx.post(LLM_URL).mock(
        return_value=completion({"quality.accuracy": 3, "quality.completeness": 4})
    )
    first = await _run(db_session, config, av, sv, output="Même sortie")
    await run_jobs()
    second = await _run(db_session, config, av, sv, output="Même sortie")
    await run_jobs()
    assert route.call_count == 1
    cached = list(
        await db_session.scalars(
            select(Evaluation).where(
                Evaluation.run_id == second.id, Evaluation.evaluator_kind == EvaluatorKind.llm_judge
            )
        )
    )
    assert cached and all(r.cached and r.cost == 0 for r in cached)
    entry = await db_session.scalar(select(JudgeCacheEntry).order_by(JudgeCacheEntry.created_at.desc()))
    await db_session.refresh(entry)
    assert entry.hits >= 1
    assert first.id != second.id


@respx.mock
async def test_failed_judge_does_not_block_the_run(db_session) -> None:
    config, av, sv, _ = await _setup(db_session)
    respx.post(LLM_URL).mock(return_value=httpx.Response(401, json={"error": {"message": "invalid key"}}))
    run = await _run(db_session, config, av, sv, output="Sortie unique " + uuid.uuid4().hex)
    await run_jobs()
    await db_session.refresh(run)
    assert run.status == RunStatus.completed
    assert run.status_detail and "en échec" in run.status_detail
    kinds = {
        e.evaluator_kind
        for e in await db_session.scalars(select(Evaluation).where(Evaluation.run_id == run.id))
    }
    assert EvaluatorKind.llm_judge not in kinds


@respx.mock
async def test_invalid_answer_gets_one_correction_retry(db_session) -> None:
    config, av, sv, _ = await _setup(db_session)
    bad = httpx.Response(
        200,
        json={
            "model": "gpt-4.1-mini",
            "choices": [{"message": {"content": "Je pense que c'est bien."}}],
            "usage": {},
        },
    )
    route = respx.post(LLM_URL).mock(
        side_effect=[bad, completion({"quality.accuracy": 1, "quality.completeness": 4})]
    )
    run = await _run(db_session, config, av, sv, output="Autre sortie " + uuid.uuid4().hex)
    await run_jobs()
    assert route.call_count == 2
    second_request = json.loads(route.calls[1].request.content)
    assert "n'est pas exploitable" in second_request["messages"][-1]["content"]
    errors = await db_session.scalars(
        select(Evaluation.errors).where(
            Evaluation.run_id == run.id, Evaluation.criterion_key == "quality.accuracy"
        )
    )
    assert any(e and e[0]["type"] == "HALLUCINATION" for e in errors)
