"""Production monitoring API: results per release, agent health, risk of a run in flight."""

from __future__ import annotations

import uuid
from datetime import timedelta

from forge.domain.enums import EventStatus, Role, RunOrigin, RunStatus, TraceEventSource, TraceEventType
from forge.infra.db import utcnow
from forge.infra.models import TraceEvent
from tests.factories import complete_with_scores, create_agent_version, create_run, create_scenario_version


async def _runs(db_session, av, sv, n, *, composite, origin=RunOrigin.observed, release=None, age_days=0.0):
    out = []
    for _ in range(n):
        run = await create_run(db_session, sv, av, origin=origin)
        run.release_id = release
        run.created_at = utcnow() - timedelta(days=age_days)
        await complete_with_scores(db_session, run, composite=composite)
        out.append(run)
    return out


async def test_results_are_grouped_by_release_and_compared_with_runs_without_one(
    client_as, db_session
) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    await _runs(db_session, av, sv, 6, composite=90.0, release="rel-good")
    await _runs(db_session, av, sv, 6, composite=40.0, release="rel-bad")
    await _runs(db_session, av, sv, 6, composite=80.0)
    await _runs(
        db_session, av, sv, 3, composite=10.0, origin=RunOrigin.benchmark
    )  # a test harness: never counted
    await db_session.commit()
    viewer = await client_as(Role.viewer)
    response = await viewer.get(
        "/api/v1/analytics/releases", params={"days": 30, "agent_id": str(av.agent_id)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["n_runs"] == 18 and body["truncated"] is False
    rows = {r["label"]: r for r in body["releases"]}
    assert set(rows) == {"rel-good", "rel-bad", "(sans release)"}
    assert rows["(sans release)"]["release_id"] is None and body["releases"][-1]["release_id"] is None
    good, bad = rows["rel-good"], rows["rel-bad"]
    assert good["pass_rate"] == 1.0 and bad["pass_rate"] == 0.0 and good["n_runs"] == 6
    assert good["vs_no_release"]["composite_delta"] > 0 > bad["vs_no_release"]["composite_delta"]
    assert good["vs_no_release"]["pass_rate_delta"] == 0.0 and bad["vs_no_release"]["pass_rate_delta"] == -1.0
    assert rows["(sans release)"]["vs_no_release"] is None


async def test_agent_health_flags_a_significant_drop_and_stays_quiet_otherwise(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    await _runs(db_session, av, sv, 40, composite=90.0, age_days=3)  # the previous period: 100 % pass
    await _runs(db_session, av, sv, 15, composite=90.0, age_days=0.1)
    await _runs(db_session, av, sv, 15, composite=30.0, age_days=0.1)  # now: 50 % pass
    quiet_av = await create_agent_version(db_session, name="Quiet agent")
    await _runs(db_session, quiet_av, sv, 40, composite=90.0, age_days=3)
    await _runs(db_session, quiet_av, sv, 30, composite=90.0, age_days=0.1)
    thin_av = await create_agent_version(db_session, name="Thin agent")
    await _runs(db_session, thin_av, sv, 3, composite=10.0, age_days=0.1)
    await db_session.commit()
    viewer = await client_as(Role.viewer)

    degraded = (await viewer.get(f"/api/v1/agents/{av.agent_id}/health")).json()
    assert (
        degraded["status"] == "degraded"
        and degraded["recent"]["n_runs"] == 30
        and degraded["previous"]["n_runs"] == 40
    )
    drop = degraded["alerts"][0]
    assert (
        drop["kind"] == "pass_rate_drop"
        and drop["recent"] == 0.5
        and drop["previous"] == 1.0
        and drop["p_value"] < 0.05
    )

    assert (await viewer.get(f"/api/v1/agents/{quiet_av.agent_id}/health")).json()["status"] == "healthy"
    thin = (await viewer.get(f"/api/v1/agents/{thin_av.agent_id}/health")).json()
    assert thin["status"] == "insufficient_data" and thin["alerts"] == []
    assert (await viewer.get(f"/api/v1/agents/{uuid.uuid4()}/health")).status_code == 404
    assert (
        await viewer.get(f"/api/v1/agents/{av.agent_id}/health", params={"window_hours": 0})
    ).status_code == 422


def _event(run, seq, type_, name, *, status=EventStatus.ok, input_=None, attrs=None):
    return TraceEvent(
        run_id=run.id, seq=seq, type=type_, name=name, source=TraceEventSource.api, status=status,
        started_at=utcnow(), offset_ms=seq * 100.0, input=input_, attributes=attrs or {},
    )  # fmt: skip


async def test_a_looping_run_is_high_risk_before_it_ends_and_a_finished_one_is_not(
    client_as, db_session
) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    live = await create_run(db_session, sv, av)
    live.status, live.started_at = RunStatus.running, utcnow() - timedelta(seconds=20)
    seq = 1
    for _ in range(3):  # the same call, three times, and it keeps failing
        db_session.add(_event(live, seq, TraceEventType.tool_call, "search", input_={"q": "refund"}))
        db_session.add(_event(live, seq + 1, TraceEventType.tool_result, "search", status=EventStatus.error))
        seq += 2
    db_session.add(
        _event(live, seq, TraceEventType.llm_call, "plan", attrs={"input_tokens": 400, "output_tokens": 100})
    )
    quiet = await create_run(db_session, sv, av)
    quiet.status, quiet.started_at = RunStatus.running, utcnow() - timedelta(seconds=5)
    db_session.add(_event(quiet, 1, TraceEventType.tool_call, "search", input_={"q": "a"}))
    done = (await _runs(db_session, av, sv, 1, composite=90.0))[0]
    await db_session.commit()
    viewer = await client_as(Role.viewer)

    risky = (await viewer.get(f"/api/v1/runs/{live.id}/risk")).json()
    assert risky["level"] == "high" and risky["finished"] is False and risky["run_status"] == "running"
    assert {s["kind"] for s in risky["signals"]} == {"tool_loop", "tool_errors"}
    assert risky["observed"]["tool_calls"] == 3 and risky["observed"]["tokens"] == 500

    assert (await viewer.get(f"/api/v1/runs/{quiet.id}/risk")).json()["level"] == "low"
    finished = (await viewer.get(f"/api/v1/runs/{done.id}/risk")).json()
    assert finished["finished"] is True and finished["level"] == "low" and finished["score"] == 0.0
    assert (await viewer.get(f"/api/v1/runs/{uuid.uuid4()}/risk")).status_code == 404


async def test_a_release_is_compared_with_its_baseline_on_observed_runs_only(client_as, db_session) -> None:
    av = await create_agent_version(db_session)
    sv = await create_scenario_version(db_session)
    release_id, baseline_id = f"rel-{uuid.uuid4().hex[:6]}", f"rel-{uuid.uuid4().hex[:6]}"
    await _runs(db_session, av, sv, 30, composite=90.0, release=baseline_id)
    await _runs(db_session, av, sv, 15, composite=90.0, release=release_id)
    await _runs(db_session, av, sv, 15, composite=30.0, release=release_id)
    # An ad hoc capture is a re-execution under today's version: it must not count for a release.
    await _runs(db_session, av, sv, 40, composite=10.0, release=release_id, origin=RunOrigin.adhoc)
    thin = f"rel-{uuid.uuid4().hex[:6]}"
    await _runs(db_session, av, sv, 3, composite=10.0, release=thin)
    await db_session.commit()
    viewer = await client_as(Role.viewer)
    url = "/api/v1/analytics/releases/compare"

    worse = (
        await viewer.get(url, params={"release_id": release_id, "baseline_release_id": baseline_id})
    ).json()
    assert (
        worse["status"] == "degraded"
        and worse["release"]["n_runs"] == 30
        and worse["baseline"]["n_runs"] == 30
    )
    assert worse["alerts"][0]["kind"] == "pass_rate_drop" and worse["alerts"][0]["recent"] == 0.5
    same = (
        await viewer.get(url, params={"release_id": baseline_id, "baseline_release_id": baseline_id})
    ).json()
    assert same["status"] == "healthy" and same["alerts"] == []
    few = (await viewer.get(url, params={"release_id": thin, "baseline_release_id": baseline_id})).json()
    assert few["status"] == "insufficient_data"
    assert (await viewer.get(url, params={"baseline_release_id": baseline_id})).status_code == 422
