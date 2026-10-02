"""Demo seed (``python -m forge.seed``): small scale, jobs processed in-process, demo agents in-process.

Run in an isolated database: ``FORGE_TEST_DATABASE=forge_test_seed uv run pytest tests/test_seed.py -q``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from forge.adapters.http import use_transport
from forge.demo_agents.app import app as demo_agents_app
from forge.domain.enums import EvaluatorKind, ExecutionStatus, FeedbackScope, RunStatus, ScenarioVisibility
from forge.infra.db import get_sessionmaker
from forge.infra.models import (
    Agent,
    AgentVersion,
    ApiKey,
    AuditEvent,
    Benchmark,
    BenchmarkExecution,
    Dataset,
    DatasetItem,
    Evaluation,
    EvaluationRun,
    Experiment,
    FeedbackReport,
    PromptVersion,
    Scenario,
    User,
)
from forge.seed import runner as seed_runner
from forge.seed.reset import ResetRefused, check_reset_allowed
from forge.seed.runner import SeedOptions, run_seed
from forge.seed.summary import render

DEMO_URL = "http://demo-agents.test"


@pytest.fixture
def demo_agents() -> Iterator[None]:
    """Every outgoing agent call is served by the in-process demo agents app."""
    with use_transport(httpx.ASGITransport(app=demo_agents_app)):
        yield


def _options(tmp_path: Path, **overrides: Any) -> SeedOptions:
    values: dict[str, Any] = {
        "scale": "small",
        "sync": True,
        "demo_agents_url": DEMO_URL,
        "credentials_path": tmp_path / "seed-credentials.json",
        "quiet": True,
        "timeout": 600.0,
        **overrides,
    }
    return SeedOptions(**values)


async def _counts() -> dict[str, int]:
    async with get_sessionmaker()() as session:
        result = {}
        for model in (
            User,
            ApiKey,
            Agent,
            AgentVersion,
            PromptVersion,
            Scenario,
            Dataset,
            DatasetItem,
            Benchmark,
            BenchmarkExecution,
            Experiment,
            EvaluationRun,
            AuditEvent,
        ):
            result[model.__tablename__] = int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
        result["human_evaluations"] = int(
            await session.scalar(
                select(func.count())
                .select_from(Evaluation)
                .where(Evaluation.evaluator_kind == EvaluatorKind.human)
            )
            or 0
        )
        return result


async def test_small_seed_runs_the_pipeline_and_is_idempotent(
    app: Any, demo_agents: None, tmp_path: Path
) -> None:
    report = await run_seed(_options(tmp_path, reset=True))
    assert report.completed
    assert report.total_created > 0

    async with get_sessionmaker()() as session:
        statuses = dict(
            (
                await session.execute(
                    select(EvaluationRun.status, func.count()).group_by(EvaluationRun.status)
                )
            ).all()
        )
        assert statuses.get(RunStatus.completed, 0) > 0
        assert set(statuses) <= {RunStatus.completed, RunStatus.failed}, statuses
        # ProductAgent 1.2 / 1.3 / 1.4, SupportAgent 1.0 / 1.1, ResearchAgent 1.0
        labels = set(
            (await session.execute(select(Agent.slug, AgentVersion.version).join(Agent))).tuples().all()
        )
        assert {("product-agent", "1.2"), ("product-agent", "1.3"), ("product-agent", "1.4")} <= labels
        assert {("support-agent", "1.0"), ("support-agent", "1.1"), ("research-agent", "1.0")} <= labels
        # prompt history: product_manager v1 → v13
        assert (
            await session.scalar(
                select(func.max(PromptVersion.version)).where(PromptVersion.name == "product_manager")
            )
            == 13
        )
        # library: variants, private, fresh and the C2 scenario of the full scale is absent in small
        visibilities = set(await session.scalars(select(Scenario.visibility)))
        assert {
            ScenarioVisibility.public,
            ScenarioVisibility.private,
            ScenarioVisibility.fresh,
        } <= visibilities
        assert await session.scalar(select(func.count()).where(Scenario.parent_scenario_id.is_not(None))) >= 2
        # benchmarks finalised with a summary
        executions = list(await session.scalars(select(BenchmarkExecution)))
        assert len(executions) == 2
        assert all(e.status == ExecutionStatus.completed for e in executions)
        # experiments compared, the v1.3 one linked to a v1.2 feedback report (improvement loop)
        experiments = {e.name: e for e in await session.scalars(select(Experiment))}
        assert set(experiments) == {
            seed_runner.EXP_PRODUCT_13,
            seed_runner.EXP_PRODUCT_14,
            seed_runner.EXP_SUPPORT,
        }
        for experiment in experiments.values():
            assert experiment.status == ExecutionStatus.completed
            assert experiment.comparison.get("composite"), experiment.name
            assert experiment.recommendation
        assert experiments[seed_runner.EXP_PRODUCT_13].source_feedback_report_id is not None
        assert experiments[seed_runner.EXP_PRODUCT_14].source_feedback_report_id is not None
        for name in (seed_runner.EXP_PRODUCT_13, seed_runner.EXP_PRODUCT_14):
            source = await session.get(FeedbackReport, experiments[name].source_feedback_report_id)
            assert source is not None, f"{name}: source feedback report deleted"
        source_13 = await session.get(
            FeedbackReport, experiments[seed_runner.EXP_PRODUCT_13].source_feedback_report_id
        )
        assert source_13 is not None and source_13.scope == FeedbackScope.run
        # human evaluations + gold dataset (calibration)
        gold = await session.scalar(select(Dataset).where(Dataset.slug == seed_runner.GOLD_DATASET_SLUG))
        assert gold is not None
        assert await session.scalar(select(func.count()).where(DatasetItem.dataset_id == gold.id)) >= 2
    assert report.reviewed_runs >= 4

    credentials = json.loads((tmp_path / "seed-credentials.json").read_text(encoding="utf-8"))
    assert {a["role"] for a in credentials["accounts"]} == {"maintainer", "editor", "evaluator", "viewer"}
    assert credentials["api_key"]["key"].startswith("fgk_")
    assert credentials["api_key"]["scopes"] == ["traces:write"]
    summary = await render(report)
    assert "Product Agent Benchmark" in summary
    assert seed_runner.EXP_PRODUCT_13 in summary

    # --- idempotency: a second run creates nothing --------------------------------------------------
    before = await _counts()
    again = await run_seed(_options(tmp_path))
    assert again.completed
    assert again.total_created == 0, again.created
    assert await _counts() == before

    # --- reset: wipes the business data and loads the demo again -------------------------------------
    reset = await run_seed(_options(tmp_path, reset=True, wait=False))
    after = await _counts()
    assert reset.created["scenario"] == before["scenarios"]
    assert after["agents"] == before["agents"] == 3
    assert after["experiments"] == 0  # --no-wait stops after launching the benchmarks
    assert after["human_evaluations"] == 0
    assert after["users"] == before["users"]  # bootstrap admin + 4 demo users, recreated
    async with get_sessionmaker()() as session:
        pending = await session.scalar(
            select(func.count()).where(EvaluationRun.status.not_in([RunStatus.completed, RunStatus.failed]))
        )
    assert pending and pending > 0


def test_reset_is_refused_in_production_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    from forge.seed import reset

    monkeypatch.setattr(reset.settings, "env", "production")
    with pytest.raises(ResetRefused):
        check_reset_allowed(confirmed=False)
    check_reset_allowed(confirmed=True)
