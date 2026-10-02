"""Dashboard and errors explorer: KPIs, trends, recent activity, filters, aggregations, redaction."""

from __future__ import annotations

from forge.domain.enums import Role, ScenarioVisibility
from forge.infra.db import get_sessionmaker
from forge.infra.models import Scenario
from forge.services.runs import mark_failed
from tests.factories import complete_with_scores, create_agent_version, create_run, create_scenario_version


async def _seed() -> dict:
    async with get_sessionmaker()() as session:
        av = await create_agent_version(session, name="DashAgent")
        public = await create_scenario_version(session, name="Public dash", category="delivery")
        private = await create_scenario_version(
            session, name="Privé dash", visibility=ScenarioVisibility.private, category="compliance"
        )
        secret = await create_scenario_version(session, name="Secret dash")
        (await session.get(Scenario, secret.scenario_id)).classification = 3
        r1 = await create_run(session, public, av)
        await complete_with_scores(session, r1, composite=90.0, errors=[("FORMAT_ERROR", "low")])
        r2 = await create_run(session, private, av)
        await complete_with_scores(session, r2, composite=50.0, errors=[("HALLUCINATION", "critical")])
        r3 = await create_run(session, public, av, repetition=1)
        await mark_failed(session, r3, "Délai dépassé", error_type="TIMEOUT")
        r4 = await create_run(session, secret, av)
        await complete_with_scores(session, r4, composite=10.0, errors=[("DATA_LEAK", "critical")])
        await session.commit()
        return {
            "agent_version": av.id,
            "public": public.scenario_id,
            "private": private.scenario_id,
            "runs": [r1.id, r2.id],
        }


async def test_dashboard(client_as) -> None:
    await _seed()
    viewer = await client_as(Role.viewer, clearance=1)
    response = await viewer.get("/api/v1/dashboard", params={"days": 7})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["days"] == 7 and len(data["trends"]) == 8
    assert data["counts"]["agents"] >= 1 and data["counts"]["runs"] >= 3
    assert data["runs_by_status"]["failed"] >= 1
    kpis = data["kpis"]
    assert 0 <= kpis["pass_rate"] <= 1 and 0 < kpis["error_rate"] <= 1 and kpis["failure_rate"] > 0
    assert kpis["average_composite"] is not None and kpis["average_latency_ms"] is not None
    types = {e["error_type"] for e in data["top_error_types"]}
    assert {"FORMAT_ERROR", "HALLUCINATION"} <= types
    # The C3 run (and its scenario) is only counted for a cleared caller.
    cleared = (
        await (await client_as(Role.viewer, clearance=3)).get("/api/v1/dashboard", params={"days": 7})
    ).json()
    assert cleared["counts"]["runs"] >= data["counts"]["runs"] + 1
    assert cleared["counts"]["scenarios"] >= data["counts"]["scenarios"] + 1
    assert set(data["queue_depth"]) == {"execution", "evaluation"}
    assert data["trends"][-1]["runs"] >= 3
    assert (await viewer.get("/api/v1/dashboard", params={"days": 0})).status_code == 422


async def test_errors_explorer_filters_and_redaction(client_as) -> None:
    ids = await _seed()
    viewer = await client_as(Role.viewer, clearance=1)
    response = await viewer.get("/api/v1/errors", params={"agent_version_id": str(ids["agent_version"])})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2  # TIMEOUT execution errors are not stored as run_errors; C3 hidden
    by_type = {t["error_type"]: t["count"] for t in data["aggregations"]["by_type"]}
    assert by_type == {"FORMAT_ERROR": 1, "HALLUCINATION": 1}
    assert data["aggregations"]["by_severity"]["critical"] == 1
    assert data["aggregations"]["critical"] == 1
    assert data["aggregations"]["by_agent_version"][0]["label"] == "DashAgent v1.0"
    private_item = next(i for i in data["items"] if i["error_type"] == "HALLUCINATION")
    assert private_item["redacted"] is True and private_item["description"] != "Erreur HALLUCINATION simulée"
    assert private_item["scenario"]["name"] == "Privé dash"  # names stay visible
    public_item = next(i for i in data["items"] if i["error_type"] == "FORMAT_ERROR")
    assert public_item["redacted"] is False and public_item["description"] == "Erreur FORMAT_ERROR simulée"

    maintainer = await client_as(Role.maintainer, clearance=3)
    full = (
        await maintainer.get("/api/v1/errors", params={"agent_version_id": str(ids["agent_version"])})
    ).json()
    assert full["total"] == 3 and all(not i["redacted"] for i in full["items"])

    filtered = (
        await viewer.get(
            "/api/v1/errors",
            params={"agent_version_id": str(ids["agent_version"]), "severity": ["critical"], "page_size": 1},
        )
    ).json()
    assert filtered["total"] == 1 and filtered["page_size"] == 1 and len(filtered["items"]) == 1
    by_category = (
        await viewer.get(
            "/api/v1/errors", params={"agent_version_id": str(ids["agent_version"]), "category": "delivery"}
        )
    ).json()
    assert [i["error_type"] for i in by_category["items"]] == ["FORMAT_ERROR"]
    by_type_filter = (
        await viewer.get(
            "/api/v1/errors",
            params={"agent_version_id": str(ids["agent_version"]), "error_type": "HALLUCINATION"},
        )
    ).json()
    assert by_type_filter["total"] == 1
    by_run = (await viewer.get("/api/v1/errors", params={"run_id": str(ids["runs"][0])})).json()
    assert by_run["total"] == 1


async def test_results_overview_aggregates_per_agent_version(db_session, client_as) -> None:
    """« Analyser › Résultats »: evaluated runs of the window, one row per agent version."""
    from forge.domain.enums import Role
    from tests.factories import (
        complete_with_scores,
        create_agent_version,
        create_run,
        create_scenario_version,
    )

    v1 = await create_agent_version(db_session, version="1.0")
    v2 = await create_agent_version(db_session, version="2.0")
    sv = await create_scenario_version(db_session)
    for rep, (version, score) in enumerate([(v1, 60.0), (v1, 64.0), (v2, 88.0), (v2, 92.0)]):
        run = await create_run(db_session, sv, version, repetition=rep)
        await complete_with_scores(
            db_session, run, composite=score, errors=[("HALLUCINATION", "high")] if version is v1 else None
        )
    await db_session.commit()

    viewer = await client_as(Role.viewer)
    response = await viewer.get("/api/v1/results/overview", params={"days": 7})
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {r["agent_version_id"]: r for r in body["agents"]}
    assert rows[str(v2.id)]["composite_mean"] == 90.0 and rows[str(v2.id)]["n_runs"] == 2
    assert rows[str(v1.id)]["composite_mean"] == 62.0
    assert rows[str(v1.id)]["errors_by_type"].get("HALLUCINATION") == 2
    assert any(e["error_type"] == "HALLUCINATION" for e in body["errors"])
    # Sorted by mean composite, best first.
    ordered = [
        r["agent_version_id"]
        for r in body["agents"]
        if r["agent_version_id"] in rows and r["agent_version_id"] in (str(v1.id), str(v2.id))
    ]
    assert ordered == [str(v2.id), str(v1.id)]
