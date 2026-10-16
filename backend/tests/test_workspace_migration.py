"""Migration 0005 (workspace model) on a *populated* database (ticket NOV-105).

A scratch database is migrated to the schema of ``main`` (revision 0004), filled with varied synthetic data
(every table that holds tenant data), then:

1. ``upgrade head`` — no row lost or modified (count + content hash of every pre-existing column), every
   row in the default workspace, every user a member of it, constraints validated, indexes valid;
2. ``downgrade`` to 0004 — the schema and the data are those of before;
3. ``upgrade head`` again, and once more after ``stamp 0004`` (resuming a half-applied migration).
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from forge.domain.enums import (
    ActorType,
    AdapterKind,
    DatasetKind,
    Difficulty,
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    EventStatus,
    ExecutionStatus,
    ExperimentArm,
    FeedbackScope,
    JobKind,
    JobQueue,
    JobStatus,
    JudgeProvider,
    ProviderKind,
    Role,
    RunOrigin,
    RunStatus,
    ScenarioVisibility,
    ScoreSource,
    TraceEventSource,
    TraceEventType,
)
from tests.conftest import BACKEND_DIR, PG_SERVER_URL

DEFAULT_WORKSPACE = "00000000-0000-4000-8000-000000000001"
BEFORE = "0004"
NEW_TABLES = {"workspaces", "projects", "workspace_members", "project_members"}
T0 = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


# --- scratch database ---------------------------------------------------------------------------------------


@pytest.fixture
def scratch_url() -> Iterator[str]:
    name = f"forge_mig_{uuid.uuid4().hex[:8]}"

    async def admin(sql: str) -> None:
        conn = await asyncpg.connect(f"{PG_SERVER_URL}/postgres", timeout=10)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    try:
        yield f"{PG_SERVER_URL}/{name}"
    finally:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def alembic(url: str, *args: str) -> None:
    env = os.environ.copy()
    env["FORGE_DATABASE_URL"] = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr[-3000:]


# --- synthetic data (raw SQL: the models of this branch know the new columns) --------------------------------


async def ins(conn: asyncpg.Connection, table: str, **row: Any) -> uuid.UUID | None:
    values = [json.dumps(v, ensure_ascii=False) if isinstance(v, dict | list) else v for v in row.values()]
    columns = ", ".join(row)
    marks = ", ".join(f"${i}" for i in range(1, len(row) + 1))
    await conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", *values)
    return row.get("id")


def uid() -> uuid.UUID:
    return uuid.uuid4()


async def populate(conn: asyncpg.Connection) -> dict[str, int]:
    n = 0
    users = []
    for i, role in enumerate(Role):
        user_id = uid()
        users.append(user_id)
        await ins(
            conn, "users", id=user_id, email=f"user{i}@exemple.test", full_name=f"Utilisateur Ünïcode {i} ✓",
            password_hash="$argon2id$synthetic", role=role.value, clearance=i % 4, active=i != 2,
            last_login_at=T0 + timedelta(days=i) if i % 2 else None,
        )  # fmt: skip
    credentials = []
    for i, kind in enumerate((ProviderKind.http, ProviderKind.openai, ProviderKind.anthropic)):
        cid = uid()
        credentials.append(cid)
        await ins(
            conn, "provider_credentials", id=cid, name=f"cred-{i}", kind=kind.value,
            base_url=None if i == 0 else "https://llm.exemple.test/v1",
            secret_encrypted=None if i == 0 else f"gAAAA-synthetic-{i}", secret_hint=None if i == 0 else "••••0000",
            created_by=users[0],
        )  # fmt: skip
    for i in range(4):
        await ins(
            conn, "api_keys", id=uid(), name=f"clé {i}", prefix=f"pre{i:05d}", key_hash=f"hash-{i}",
            role=(Role.viewer, Role.editor, Role.admin, Role.evaluator)[i].value, clearance=i % 4,
            scopes=["traces:write"] if i == 1 else [], created_by=users[1],
            expires_at=T0 + timedelta(days=30) if i == 2 else None, revoked_at=T0 if i == 3 else None,
        )  # fmt: skip
    models, prompts, tools = [], [], []
    for i in range(3):
        mid = uid()
        models.append(mid)
        await ins(
            conn, "model_configurations", id=mid, name=f"modèle {i}", provider="openai", model=f"gpt-{i}",
            temperature=0.1 * i, params={"seed": i, "stop": ["\n\n"]}, content_hash=f"mc-{i}",
        )  # fmt: skip
    for i in range(4):
        pid = uid()
        prompts.append(pid)
        await ins(
            conn, "prompt_versions", id=pid, name=f"prompt-{i % 2}", version=i // 2 + 1,
            content=f"Tu es un assistant n°{i}. «Réponds» en français — 日本語 ok.", variables=["x"], content_hash=f"pv-{i}",
        )  # fmt: skip
    for i in range(2):
        tid = uid()
        tools.append(tid)
        await ins(
            conn, "tool_configurations", id=tid, name=f"tools-{i}", version=1,
            tools=[{"name": "search", "parameters": {"type": "object"}}], content_hash=f"tc-{i}",
        )  # fmt: skip

    agents, versions = [], []
    for i in range(5):
        aid = uid()
        agents.append(aid)
        await ins(
            conn, "agents", id=aid, slug=f"agent-{i}", name=f"Agent {i}", provider="NOVA", owner_id=users[0],
            tags=["a", "b"], metadata={"équipe": f"t{i}"}, archived=i == 4,
        )  # fmt: skip
        for v in range(3):
            vid = uid()
            versions.append((vid, aid))
            await ins(
                conn, "agent_versions", id=vid, agent_id=aid, version=f"1.{v}", version_number=v + 1,
                adapter_kind=(AdapterKind.mock, AdapterKind.mock, AdapterKind.mock)[v].value,
                model_configuration_id=models[v], prompt_version_id=prompts[v],
                tool_configuration_id=tools[v % 2] if v else None, system_prompt="Prompt système " * (v + 1),
                context_config={"k": v}, adapter_config={"mock": True}, budget={"max_tokens": 1000 * (v + 1)},
                credential_id=credentials[v] if v == 2 else None, contamination=[], content_hash=f"av-{i}-{v}",
                created_by=users[1],
            )  # fmt: skip

    datasets = []
    for i, kind in enumerate((DatasetKind.context, DatasetKind.gold, DatasetKind.context)):
        did = uid()
        datasets.append(did)
        await ins(conn, "datasets", id=did, slug=f"ds-{i}", name=f"Jeu {i}", kind=kind.value, tags=["t"])
    scenarios, scenario_versions = [], []
    for i in range(20):
        sid = uid()
        scenarios.append(sid)
        await ins(
            conn, "scenarios", id=sid, slug=f"scn-{i}", name=f"Scénario {i} « test »", category="product_management",
            family_id=sid, visibility=(ScenarioVisibility.public if i % 3 else ScenarioVisibility.private).value,
            classification=i % 4, tags=["x"], latest_version=2, fresh_until=T0 + timedelta(days=i) if i % 5 == 0 else None,
        )  # fmt: skip
        for v in (1, 2):
            svid = uid()
            scenario_versions.append((svid, sid))
            await ins(
                conn, "scenario_versions", id=svid, scenario_id=sid, version=v, difficulty=Difficulty.medium.value,
                input={"prompt": f"Rédige le PRD {i}.{v}"}, context={}, constraints=["court"],
                expected_output=json.dumps("Un PRD") if v == 1 else None, criteria=[], rules=[{"id": "r", "type": "no_canary"}],
                tool_mocks=[], dataset_id=datasets[0] if i % 4 == 0 else None, canary=f"CANARY-{i}-{v}",
                content_hash=f"sv-{i}-{v}",
            )  # fmt: skip
    await ins(conn, "criteria", key="quality.accuracy", dimension=Dimension.quality.value, name="Exactitude")
    await ins(conn, "criteria", key="safety.leak", dimension=Dimension.safety.value, name="Fuite")
    for code in ("FORMAT_ERROR", "HALLUCINATION", "TIMEOUT"):
        await ins(
            conn, "error_types", code=code, label=code.title(), default_severity=ErrorSeverity.low.value,
            dimension=Dimension.quality.value,
        )  # fmt: skip

    judges, configs = [], []
    for i in range(3):
        jid = uid()
        judges.append(jid)
        await ins(
            conn, "judges", id=jid, key=f"judge-{i}", version=1, name=f"Juge {i}",
            provider=JudgeProvider.heuristic.value, model="heuristic-v1", system_prompt="Évalue.",
            criteria=["quality.accuracy"], credential_id=None, content_hash=f"j-{i}",
        )  # fmt: skip
    for i in range(3):
        cid = uid()
        configs.append(cid)
        await ins(
            conn, "evaluation_configs", id=cid, key=f"cfg-{i}", version=1, name=f"Config {i}",
            dimension_weights={"quality": 0.5, "safety": 0.5}, judge_ids=[str(judges[i])], is_default=i == 0,
            gates=[{"dimension": "safety", "min": 0.5}], content_hash=f"ec-{i}",
        )  # fmt: skip

    benchmarks = []
    for i in range(2):
        bid = uid()
        benchmarks.append(bid)
        await ins(
            conn, "benchmarks", id=bid, slug=f"bench-{i}", name=f"Benchmark {i}", evaluation_config_id=configs[0],
            repetitions=2, tags=["b"], created_by=users[1],
        )  # fmt: skip
        for p, (svid, sid) in enumerate(scenario_versions[:12:2]):
            await ins(
                conn, "benchmark_scenarios", benchmark_id=bid, scenario_id=sid,
                scenario_version_id=svid if p % 2 else None, position=p,
            )  # fmt: skip
        for p, (vid, _) in enumerate(versions[:3]):
            await ins(conn, "benchmark_agents", benchmark_id=bid, agent_version_id=vid, position=p)
    executions = []
    for i in range(2):
        eid = uid()
        executions.append(eid)
        await ins(
            conn, "benchmark_executions", id=eid, benchmark_id=benchmarks[0], number=i + 1,
            status=ExecutionStatus.completed.value, evaluation_config_id=configs[0], repetitions=2,
            matrix={"scenario_version_ids": [], "agent_version_ids": []}, total_runs=30, completed_runs=29,
            failed_runs=1, summary={"ranking": []}, started_at=T0, finished_at=T0 + timedelta(hours=1),
        )  # fmt: skip
    experiments = []
    for i in range(2):
        xid = uid()
        experiments.append(xid)
        await ins(
            conn, "experiments", id=xid, name=f"Expérience {i}", baseline_version_id=versions[0][0],
            candidate_version_id=versions[1][0], benchmark_id=benchmarks[0], evaluation_config_id=configs[0],
            status=ExecutionStatus.completed.value, comparison={"verdict": "ship"}, recommendation="ship",
            tags=[], created_by=users[1],
        )  # fmt: skip
        for p, (svid, sid) in enumerate(scenario_versions[:4]):
            await ins(
                conn, "experiment_scenarios", experiment_id=xid, scenario_version_id=svid, scenario_id=sid, position=p
            )  # fmt: skip

    runs = []
    for i in range(60):
        rid = uid()
        runs.append(rid)
        svid, sid = scenario_versions[i % len(scenario_versions)]
        vid, aid = versions[i % len(versions)]
        origin = (RunOrigin.adhoc, RunOrigin.benchmark, RunOrigin.experiment, RunOrigin.observed)[i % 4]
        status = (RunStatus.completed, RunStatus.completed, RunStatus.failed, RunStatus.pending)[i % 4]
        await ins(
            conn, "evaluation_runs", id=rid, origin=origin.value,
            benchmark_execution_id=executions[0] if origin == RunOrigin.benchmark else None,
            experiment_id=experiments[0] if origin == RunOrigin.experiment else None,
            arm=ExperimentArm.baseline.value if origin == RunOrigin.experiment else None, scenario_id=sid,
            scenario_version_id=svid, agent_id=aid, agent_version_id=vid, evaluation_config_id=configs[i % 3],
            repetition=i % 3, status=status.value, error="timeout" if status == RunStatus.failed else None,
            manifest={"scenario": {"input": {"prompt": f"p{i}"}}, "unicode": "é—✓"}, manifest_hash=f"mh-{i}",
            otel_trace_id=f"{i:032x}", evaluation_round=1, composite_score=50.0 + i / 2, passed=i % 2 == 0,
            tags=["smoke"] if i % 5 == 0 else [], external_id=f"ext-{i}" if origin == RunOrigin.observed else None,
            context_snapshot_id=f"snap@v{i}" if i % 7 == 0 else None, release_id="rel-1" if i % 7 == 0 else None,
            source_manifest={"reported": True} if i % 7 == 0 else None, created_by=users[1],
            queued_at=T0, started_at=T0, finished_at=T0 + timedelta(seconds=i),
        )  # fmt: skip
        await ins(
            conn, "execution_traces", id=uid(), run_id=rid, started_at=T0, completed_at=T0 + timedelta(seconds=2),
            total_latency_ms=2000.0 + i, input={"input": {"prompt": f"p{i}"}}, output_text=f"Réponse {i} — «ok»",
            output_json={"k": [1, 2, i]}, messages=[{"role": "user", "content": "salut"}], input_tokens=100 + i,
            output_tokens=50, total_tokens=150 + i, estimated_cost=0.001 * i, model_calls=1, tool_calls=1, event_count=8,
        )  # fmt: skip
        event_ids = []
        for seq in range(1, 9):
            eid = uid()
            event_ids.append(eid)
            await ins(
                conn, "trace_events", id=eid, run_id=rid, seq=seq, parent_id=event_ids[0] if seq > 2 else None,
                type=(TraceEventType.run_started if seq == 1 else TraceEventType.final_answer if seq == 8 else TraceEventType.llm_call).value,
                name=f"étape {seq}", source=TraceEventSource.runner.value,
                status=(EventStatus.ok if seq % 5 else EventStatus.error).value, started_at=T0 + timedelta(milliseconds=seq),
                offset_ms=float(seq), duration_ms=None if seq == 8 else 1.5, input={"q": seq} if seq % 2 else None,
                output=None if seq % 2 else {"a": [seq]}, attributes={"model": "m", "span": seq},
                span_id=f"s{seq}", parent_span_id=f"s{seq - 1}" if seq > 1 else None,
            )  # fmt: skip
        eval_ids = []
        for k in range(4):
            evid = uid()
            eval_ids.append(evid)
            await ins(
                conn, "evaluations", id=evid, run_id=rid, round=1, evaluation_config_id=configs[i % 3],
                evaluator_kind=EvaluatorKind.rule.value if k < 2 else EvaluatorKind.llm_judge.value,
                evaluator_key=f"ev-{k}", criterion_key=f"quality.c{k}", dimension=Dimension.quality.value,
                raw_score=3.5, scale_min=0.0, scale_max=5.0, normalized_score=0.7, confidence=0.9,
                explanation=f"Parce que {k} — évidence «x»", evidence=[{"excerpt": "x", "trace_event_seq": 3}],
                errors=[], passed=k % 2 == 0, judge_id=judges[0] if k >= 2 else None,
                raw_response={"raw": "json"} if k == 3 else None, cached=k == 3,
            )  # fmt: skip
        for k in range(3):
            await ins(
                conn, "scores", id=uid(), run_id=rid, round=1, evaluation_config_id=configs[i % 3],
                criterion_key=f"quality.c{k}", dimension=Dimension.quality.value, value=0.6 + k / 10, weight=1.0,
                source=ScoreSource.ai.value, confidence=0.9, explanation="Score expliqué", method="single_judge",
                evaluation_ids=[str(e) for e in eval_ids[:2]],
            )  # fmt: skip
        await ins(
            conn, "composite_scores", id=uid(), run_id=rid, round=1, evaluation_config_id=configs[i % 3],
            value=60.0 + i / 3, raw_value=62.0, passed=i % 2 == 0, gate_failed=False,
            dimensions=[{"dimension": "quality", "value": 0.6}], formula="Σ w·s",
        )  # fmt: skip
        if i % 3 == 0:
            await ins(
                conn, "run_errors", id=uid(), run_id=rid, round=1, error_type="FORMAT_ERROR",
                severity=ErrorSeverity.low.value, description="Format incorrect",
                evaluator_kind=EvaluatorKind.rule.value, evaluator_key="rule-format", evaluation_id=eval_ids[0],
                trace_event_id=event_ids[2],
            )  # fmt: skip
        if i % 12 == 0:
            await ins(
                conn, "jobs", id=uid(), kind=JobKind.execute_run.value, queue=JobQueue.execution.value,
                status=JobStatus.succeeded.value, run_id=rid, payload={"i": i}, dedupe_key=f"execute_run:{rid}",
            )  # fmt: skip
        n += 1
    for i in range(5):
        await ins(
            conn, "feedback_reports", id=uid(), scope=(FeedbackScope.run if i % 2 else FeedbackScope.experiment).value,
            run_id=runs[i] if i % 2 else None, experiment_id=experiments[0] if not i % 2 else None, summary=f"Bilan {i}",
            strengths=["clair"], weaknesses=["long"], errors=[], recommendations=[], priority_actions=[], generator="builder",
        )  # fmt: skip
    for i in range(6):
        await ins(
            conn, "judge_cache", key=f"judge:{i:064x}", judge_id=judges[i % 3], response={"items": [i]}, hits=i
        )  # fmt: skip
    for i in range(30):
        await ins(
            conn, "jobs", id=uid(), kind=JobKind.evaluate_run.value, queue=JobQueue.evaluation.value,
            status=(JobStatus.queued if i % 2 else JobStatus.failed).value, priority=i % 5, error="boom" if i % 2 == 0 else None,
        )  # fmt: skip
    for i in range(4):
        await ins(
            conn, "dataset_items", id=uid(), dataset_id=datasets[1], key=f"gold-{i}", content={"note": "ok"}, run_id=runs[i]
        )  # fmt: skip
        await ins(
            conn, "dataset_items", id=uid(), dataset_id=datasets[0], key=f"doc-{i}",
            content={"title": f"Doc {i}", "content": "Texte accentué é à ü", "source": "wiki"},
        )  # fmt: skip
    for i in range(25):
        await ins(
            conn, "audit_events", id=uid(), actor_type=(ActorType.user if i % 2 else ActorType.system).value,
            actor_id=users[0] if i % 2 else None, actor_label="Admin", action="agent.create", target_type="agent",
            target_id=str(agents[i % 5]), summary=f"Création {i}", details={"i": i}, request_id=f"req-{i}",
        )  # fmt: skip
    return {"runs": n}


# --- snapshots ------------------------------------------------------------------------------------------------


async def tables_and_columns(conn: asyncpg.Connection) -> dict[str, list[str]]:
    rows = await conn.fetch(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public' "
        "AND table_name <> 'alembic_version' ORDER BY table_name, ordinal_position"
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        out.setdefault(row["table_name"], []).append(row["column_name"])
    return out


async def snapshot(conn: asyncpg.Connection, schema: dict[str, list[str]]) -> dict[str, tuple[int, str]]:
    """(row count, content hash) of each table over the given (pre-existing) columns only."""
    out: dict[str, tuple[int, str]] = {}
    for table, columns in schema.items():
        cols = ", ".join(f'"{c}"' for c in columns)
        row = await conn.fetchrow(
            f"SELECT count(*) AS n, md5(coalesce(string_agg(r, '|' ORDER BY r), '')) AS h "
            f"FROM (SELECT ROW({cols})::text AS r FROM {table}) s"
        )
        assert row is not None
        out[table] = (row["n"], row["h"])
    return out


async def read(url: str, work: Any) -> Any:
    conn = await asyncpg.connect(url, timeout=10)
    try:
        return await work(conn)
    finally:
        await conn.close()


async def assert_workspace_state(conn: asyncpg.Connection, before: dict[str, tuple[int, str]]) -> None:
    for table in before:
        if table in {
            "criteria",
            "error_types",
            "benchmark_scenarios",
            "benchmark_agents",
            "experiment_scenarios",
            "users",
        }:
            continue
        foreign = await conn.fetchval(
            f"SELECT count(*) FROM {table} WHERE workspace_id <> '{DEFAULT_WORKSPACE}'"
        )
        assert foreign == 0, table
        assert await conn.fetchval(f"SELECT count(*) FROM {table} WHERE workspace_id IS NULL") == 0, table
        if await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns WHERE table_name = $1 AND column_name = 'project_id'",
            table,
        ):
            assert await conn.fetchval(f"SELECT count(*) FROM {table} WHERE project_id IS NOT NULL") == 0, (
                table
            )
    assert await conn.fetchval("SELECT count(*) FROM workspaces") == 1
    assert (
        await conn.fetchval("SELECT slug FROM workspaces WHERE id = $1", uuid.UUID(DEFAULT_WORKSPACE))
        == "default"
    )
    assert await conn.fetchval("SELECT count(*) FROM workspace_members") == before["users"][0]
    assert (
        await conn.fetchval("SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND NOT convalidated")
        == 0
    )
    assert await conn.fetchval("SELECT count(*) FROM pg_index WHERE NOT indisvalid") == 0
    assert await conn.fetchval("SELECT count(*) FROM alembic_version") == 1


def test_the_migration_history_has_a_single_head() -> None:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(Path(BACKEND_DIR / "alembic")))
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1


def test_migration_on_a_populated_database(scratch_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    alembic(scratch_url, "upgrade", BEFORE)
    schema_before = asyncio.run(read(scratch_url, tables_and_columns))
    assert NEW_TABLES.isdisjoint(schema_before) and "workspace_id" not in itertools.chain.from_iterable(
        schema_before.values()
    )

    asyncio.run(read(scratch_url, populate))
    before = asyncio.run(read(scratch_url, lambda c: snapshot(c, schema_before)))
    total = sum(count for count, _ in before.values())
    assert before["evaluation_runs"][0] == 60 and before["trace_events"][0] == 480 and total > 1300
    assert all(count > 0 for count, _ in before.values()), [t for t, (c, _) in before.items() if not c]

    # 1. upgrade: nothing lost, nothing modified outside the new columns -------------------------------------
    alembic(scratch_url, "upgrade", "head")
    after = asyncio.run(read(scratch_url, lambda c: snapshot(c, schema_before)))
    assert after == before
    schema_after = asyncio.run(read(scratch_url, tables_and_columns))
    assert set(schema_after) >= NEW_TABLES
    assert {t for t, cols in schema_after.items() if "workspace_id" in cols} >= set(schema_before) - {
        "criteria", "error_types", "benchmark_scenarios", "benchmark_agents", "experiment_scenarios", "users",
    }  # fmt: skip
    asyncio.run(read(scratch_url, lambda c: assert_workspace_state(c, before)))

    # 2. downgrade: the schema and the data of before ---------------------------------------------------------
    alembic(scratch_url, "downgrade", BEFORE)
    assert asyncio.run(read(scratch_url, tables_and_columns)) == schema_before
    assert asyncio.run(read(scratch_url, lambda c: snapshot(c, schema_before))) == before

    # 3. upgrade again, then resume a migration whose version stamp was lost ----------------------------------
    alembic(scratch_url, "upgrade", "head")
    assert asyncio.run(read(scratch_url, lambda c: snapshot(c, schema_before))) == before
    asyncio.run(read(scratch_url, lambda c: assert_workspace_state(c, before)))
    alembic(scratch_url, "stamp", BEFORE)
    alembic(scratch_url, "upgrade", "head")  # every step is idempotent
    assert asyncio.run(read(scratch_url, lambda c: snapshot(c, schema_before))) == before
    asyncio.run(read(scratch_url, lambda c: assert_workspace_state(c, before)))

    with capsys.disabled():
        print(
            f"\n[migration 0005] populated base: {len(before)} tables, {total} rows "
            f"({before['evaluation_runs'][0]} runs, {before['trace_events'][0]} events, "
            f"{before['evaluations'][0]} evaluations); after upgrade / downgrade / upgrade: identical "
            "counts and content hashes of every existing column; 0 row outside the default workspace."
        )


def test_migration_0006_external_identities_on_a_populated_database(scratch_url: str) -> None:
    """NOV-108: one new table; nothing existing moves. Up, down, up again, and resumed after a lost stamp."""
    alembic(scratch_url, "upgrade", "0005")
    schema = asyncio.run(read(scratch_url, tables_and_columns))
    asyncio.run(read(scratch_url, populate))
    before = asyncio.run(read(scratch_url, lambda c: snapshot(c, schema)))

    async def table_exists(conn: asyncpg.Connection) -> bool:
        return bool(await conn.fetchval("SELECT to_regclass('public.external_identities') IS NOT NULL"))

    async def link_one(conn: asyncpg.Connection) -> None:
        user_id = await conn.fetchval("SELECT id FROM users LIMIT 1")
        await conn.execute(
            "INSERT INTO external_identities (issuer, sub, user_id) VALUES ('https://idp.test/realms/orion', 's1', $1)",
            user_id,
        )
        with pytest.raises(asyncpg.UniqueViolationError):  # one identity per (issuer, user)
            await conn.execute(
                "INSERT INTO external_identities (issuer, sub, user_id) VALUES ('https://idp.test/realms/orion', 's2', $1)",
                user_id,
            )

    alembic(scratch_url, "upgrade", "head")
    assert asyncio.run(read(scratch_url, table_exists))
    assert asyncio.run(read(scratch_url, lambda c: snapshot(c, schema))) == before
    asyncio.run(read(scratch_url, link_one))
    alembic(scratch_url, "downgrade", "0005")
    assert not asyncio.run(read(scratch_url, table_exists))
    assert asyncio.run(read(scratch_url, lambda c: snapshot(c, schema))) == before
    alembic(scratch_url, "upgrade", "head")
    alembic(scratch_url, "stamp", "0005")
    alembic(scratch_url, "upgrade", "head")  # idempotent
    assert asyncio.run(read(scratch_url, lambda c: snapshot(c, schema))) == before
