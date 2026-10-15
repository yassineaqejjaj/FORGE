"""Observability: deployed commit, queue / pending-capture gauges on /metrics, Prometheus alert rules."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import yaml
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import update

from forge.config import settings
from forge.domain.enums import JobStatus, RunOrigin, RunStatus
from forge.infra.db import utcnow
from forge.infra.models import EvaluationRun, Job
from forge.infra.observability import metrics
from tests.factories import create_agent_version, create_run, create_scenario_version

ALERTS = Path(__file__).resolve().parents[2] / "deploy" / "alerts.yml"


def sample(body: str, name: str, **labels: str) -> float | None:
    for family in text_string_to_metric_families(body):
        for s in family.samples:
            if s.name == name and all(s.labels.get(k) == v for k, v in labels.items()):
                return s.value
    return None


async def test_health_and_ready_expose_the_deployed_commit(client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "git_sha", "0123456789abcdef0123456789abcdef01234567")
    health = (await client.get("/health")).json()
    ready = (await client.get("/ready")).json()
    assert health["git_sha"] == ready["git_sha"] == "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setattr(settings, "git_sha", "")
    assert (await client.get("/health")).json()["git_sha"] is None


def test_git_sha_comes_from_the_build_environment(monkeypatch) -> None:
    from forge.config import Settings

    for name in ("FORGE_GIT_SHA", "GIT_SHA", "RAILWAY_GIT_COMMIT_SHA"):
        monkeypatch.delenv(name, raising=False)
    assert Settings().git_sha == ""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "railway-sha")
    assert Settings().git_sha == "railway-sha"
    monkeypatch.setenv("GIT_SHA", "")  # an empty build arg must not hide the platform variable
    assert Settings().git_sha == "railway-sha"
    monkeypatch.setenv("GIT_SHA", "build-arg-sha")
    assert Settings().git_sha == "build-arg-sha"
    monkeypatch.setenv("FORGE_GIT_SHA", "explicit")
    assert Settings().git_sha == "explicit"


async def test_metrics_expose_queue_age_and_pending_observed_captures(client, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    queued = await create_run(db_session, sv, av, enqueue=True)
    observed = await create_run(db_session, sv, av, origin=RunOrigin.observed, repetition=1)
    observed.status = RunStatus.evaluating
    done = await create_run(db_session, sv, av, origin=RunOrigin.observed, repetition=2)
    done.status = RunStatus.completed
    await db_session.execute(
        update(Job).where(Job.run_id == queued.id).values(created_at=utcnow() - timedelta(minutes=10))
    )
    await db_session.commit()
    body = (await client.get("/metrics")).text
    assert (sample(body, "forge_queue_depth", queue="execution") or 0) >= 1
    assert sample(body, "forge_queue_depth", queue="evaluation") is not None
    assert (sample(body, "forge_oldest_job_age_seconds", queue="execution") or 0) >= 590
    assert (sample(body, "forge_observed_pending_evaluations") or 0) >= 1
    await db_session.execute(
        update(Job).where(Job.status == JobStatus.queued).values(status=JobStatus.cancelled)
    )
    await db_session.execute(
        update(EvaluationRun)
        .where(EvaluationRun.origin == RunOrigin.observed)
        .values(status=RunStatus.completed)
    )
    await db_session.commit()
    drained = (await client.get("/metrics")).text
    assert sample(drained, "forge_queue_depth", queue="execution") == 0
    assert sample(drained, "forge_oldest_job_age_seconds", queue="execution") == 0
    assert sample(drained, "forge_observed_pending_evaluations") == 0


# --- Alert rules ------------------------------------------------------------------------------------


def _rules() -> list[dict]:
    groups = yaml.safe_load(ALERTS.read_text(encoding="utf-8"))["groups"]
    return [rule for group in groups for rule in group["rules"]]


def _exported() -> set[str]:
    """Every metric name FORGE can export (HELP/TYPE lines exist even before the first sample)."""
    text = generate_latest().decode()
    names = set(re.findall(r"^# (?:HELP|TYPE) (\S+) ", text, re.M))
    return names | {n.removesuffix("_total") for n in names}


def test_alert_rules_are_well_formed() -> None:
    rules = _rules()
    assert rules and all({"alert", "expr", "labels", "annotations"} <= set(r) for r in rules)
    assert len({r["alert"] for r in rules}) == len(rules)
    assert all(r["labels"].get("severity") in {"warning", "critical"} for r in rules)


def test_every_metric_referenced_by_an_alert_exists() -> None:
    known = _exported()
    for rule in _rules():
        for name in re.findall(r"\bforge_[a-z_]+", rule["expr"]):
            assert name in known, f"{rule['alert']}: {name}"


def test_judge_alert_selects_outcomes_the_code_emits() -> None:
    rule = next(r for r in _rules() if "forge_judge_calls_total" in r["expr"])
    used = set()
    for match in re.finditer(r'outcome(=~|!=|=)"([^"]+)"', rule["expr"]):
        assert match.group(1) != "!=", "negative matchers are true for every unknown outcome"
        used |= set(match.group(2).split("|"))
    assert used and used <= set(metrics.JUDGE_OUTCOMES)
    assert '"ok"' not in rule["expr"]  # the code never emits outcome="ok"


def test_documented_alerts_use_the_real_outcome_label() -> None:
    docs = (Path(__file__).resolve().parents[2] / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    assert 'outcome!="ok"' not in docs
