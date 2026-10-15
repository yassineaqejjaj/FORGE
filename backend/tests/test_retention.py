"""Retention (scheduled purge) and forgetting (API + signed ORBIT webhook): texts go, measurements stay."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text

from forge.config import settings
from forge.domain.enums import ErrorSeverity, EvaluatorKind, Role
from forge.infra.db import get_sessionmaker, utcnow
from forge.infra.models import (
    AuditEvent,
    Evaluation,
    EvaluationRun,
    ExecutionTrace,
    FeedbackReport,
    Judge,
    JudgeCacheEntry,
    ScenarioVersion,
    Score,
    TraceEvent,
)
from forge.services import retention
from tests.factories import (
    attach_trace,
    complete_with_scores,
    create_agent_version,
    create_run,
    create_scenario_version,
)

SECRET_TEXT = "REMISE SYNTHETIQUE 35 % pour le client fictif"


def _doc(document_id: str, **extra) -> dict:
    return {
        "id": f"chunk-{uuid.uuid4().hex[:6]}",
        "title": "Contrat fictif",
        "content": SECRET_TEXT,
        "classification": 3,
        "document_id": document_id,
        **extra,
    }


async def _seed(session, *, documents: list[dict], finished_days_ago: float = 0.0, external_id=None) -> dict:
    """A run that received ``documents``, with trace, events, scores, judge answer, feedback and manifest."""
    av = await create_agent_version(session)
    sv = await create_scenario_version(session, context={"documents": documents})
    run = await create_run(session, sv, av)
    run.external_id = external_id
    trace = await attach_trace(
        session,
        run,
        output_text=f"Réponse citant : {SECRET_TEXT}",
        events=[
            {"type": "llm_call", "name": "Génération", "input": {"q": SECRET_TEXT}, "output": SECRET_TEXT}
        ],
    )
    trace.input = {"input": {"prompt": "x"}, "context": {"documents": documents}}
    trace.messages = [{"role": "user", "content": SECRET_TEXT}]
    await complete_with_scores(session, run, composite=72.0)
    run.finished_at = utcnow() - timedelta(days=finished_days_ago)
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
    await session.flush()
    session.add(
        Evaluation(
            run_id=run.id,
            round=1,
            evaluator_kind=EvaluatorKind.llm_judge,
            evaluator_key=f"{judge.key}@v1",
            criterion_key="quality.accuracy",
            dimension="quality",
            raw_score=4.0,
            scale_min=0.0,
            scale_max=5.0,
            normalized_score=0.8,
            confidence=0.9,
            explanation="Justification.",
            judge_id=judge.id,
            raw_response={"prompt": {"user": SECRET_TEXT}, "answer": SECRET_TEXT},
        )
    )
    session.add(
        JudgeCacheEntry(
            key=f"k-{uuid.uuid4().hex}",
            judge_id=judge.id,
            response={"text": SECRET_TEXT},
            created_at=utcnow() - timedelta(days=finished_days_ago),
        )
    )
    session.add(
        FeedbackReport(
            scope="run",
            run_id=run.id,
            round=1,
            score=72.0,
            summary="Synthèse.",
            strengths=[],
            weaknesses=[],
            errors=[
                {
                    "type": "HALLUCINATION",
                    "severity": ErrorSeverity.high.value,
                    "count": 1,
                    "description": SECRET_TEXT,
                    "examples": [SECRET_TEXT],
                    "evidence": [{"excerpt": SECRET_TEXT}],
                }
            ],
            recommendations=[{"title": "Citer", "evidence": [{"excerpt": SECRET_TEXT}]}],
            priority_actions=[],
            generator="deterministic",
            created_at=utcnow() - timedelta(days=finished_days_ago),
        )
    )
    await session.commit()
    return {"run": run.id, "sv": sv.id, "judge": judge.id}


async def _state(run_id, *, manifest: bool = True) -> dict:
    async with get_sessionmaker()() as session:
        trace = await session.scalar(select(ExecutionTrace).where(ExecutionTrace.run_id == run_id))
        events = list(await session.scalars(select(TraceEvent).where(TraceEvent.run_id == run_id)))
        evaluation = await session.scalar(select(Evaluation).where(Evaluation.run_id == run_id))
        feedback = await session.scalar(select(FeedbackReport).where(FeedbackReport.run_id == run_id))
        run = await session.get(EvaluationRun, run_id)
        scores = list(await session.scalars(select(Score).where(Score.run_id == run_id)))
        return {
            "trace": trace, "events": events, "evaluation": evaluation, "feedback": feedback, "run": run,
            "scores": scores, "payload": json.dumps([trace.input, trace.output_text, trace.messages,
                [(e.input, e.output) for e in events], evaluation.raw_response, feedback.errors,
                feedback.recommendations, run.manifest if manifest else None], default=str),
        }  # fmt: skip


def _assert_measurements_kept(state: dict) -> None:
    assert state["run"].composite_score == pytest.approx(72.0) and state["scores"]
    assert state["trace"].total_tokens == 1800 and state["trace"].estimated_cost == pytest.approx(0.012)
    assert state["evaluation"].normalized_score == pytest.approx(0.8)
    assert state["evaluation"].explanation == "Justification."
    assert {e.name for e in state["events"]} >= {"Génération", "Réponse finale"}  # timeline structure
    assert state["feedback"].score == 72.0 and state["feedback"].errors[0]["type"] == "HALLUCINATION"


# --- Forget -----------------------------------------------------------------------------------------


async def test_forget_by_document_empties_every_copy_and_keeps_the_measurement(db_session) -> None:
    document_id = str(uuid.uuid4())
    concerned = await _seed(db_session, documents=[_doc(document_id)])
    other = await _seed(db_session, documents=[_doc(str(uuid.uuid4()))])
    before_other = (await _state(other["run"]))["payload"]

    async with get_sessionmaker()() as session:
        receipt = await retention.forget(session, retention.ForgetRequest(document_ids=[document_id]))
        await session.commit()
    assert receipt.runs == 1 and receipt.traces == 1 and receipt.evaluations == 1
    assert receipt.trace_events >= 2 and receipt.scenario_versions == 1 and receipt.manifests == 1
    assert receipt.feedback_reports == 1 and receipt.judge_cache_entries >= 1

    state = await _state(concerned["run"])
    assert SECRET_TEXT not in state["payload"]
    assert state["trace"].input == {} and state["trace"].metadata_["purged_at"]
    _assert_measurements_kept(state)
    async with get_sessionmaker()() as session:
        version = await session.get(ScenarioVersion, concerned["sv"])
        doc = version.context["documents"][0]
        assert doc["content"] == "" and doc["forgotten"] is True and doc["document_id"] == document_id
        assert doc["classification"] == 3  # provenance and level are kept
        assert await session.scalar(select(func.count()).select_from(JudgeCacheEntry)) == 0
        audit = await session.scalar(select(AuditEvent).where(AuditEvent.action == "forget.apply"))
        assert audit.details["document_ids"] == [document_id] and SECRET_TEXT not in json.dumps(audit.details)
    assert (await _state(other["run"]))["payload"] == before_other  # unrelated runs are untouched

    async with get_sessionmaker()() as session:  # idempotent
        again = await retention.forget(session, retention.ForgetRequest(document_ids=[document_id]))
        assert again.total() == 0 and again.traces == again.evaluations == again.scenario_versions == 0


async def test_forget_by_memory_item_lineage_and_task(db_session) -> None:
    memory_id, lineage = str(uuid.uuid4()), str(uuid.uuid4())
    by_memory = await _seed(db_session, documents=[_doc("x", memory_item_id=memory_id, id=memory_id)])
    by_lineage = await _seed(db_session, documents=[_doc("y", key=f"memory:{lineage}")])
    task = str(uuid.uuid4())
    by_task = await _seed(db_session, documents=[_doc("z")], external_id=f"nova-sdlc:{task}")
    async with get_sessionmaker()() as session:
        receipt = await retention.forget(
            session,
            retention.ForgetRequest(memory_item_ids=[memory_id], lineage_ids=[lineage], task_ids=[task]),
        )
        await session.commit()
    assert receipt.runs == 3
    for seeded in (by_memory, by_lineage):
        assert SECRET_TEXT not in (await _state(seeded["run"]))["payload"]
    # A task names a run, not a document: the run's payloads go, the scenario's own content stays.
    assert SECRET_TEXT not in (await _state(by_task["run"], manifest=False))["payload"]


async def test_forget_validates_its_input() -> None:
    async with get_sessionmaker()() as session:
        with pytest.raises(retention.InvalidError):
            await retention.forget(session, retention.ForgetRequest())
        with pytest.raises(retention.InvalidError):
            await retention.forget(
                session, retention.ForgetRequest(document_ids=[str(i) for i in range(201)])
            )


async def test_forget_endpoint_is_admin_only(client_as, db_session) -> None:
    document_id = str(uuid.uuid4())
    seeded = await _seed(db_session, documents=[_doc(document_id)])
    body = {"document_ids": [document_id], "reason": "demande ORBIT"}
    for role in (Role.viewer, Role.editor, Role.maintainer):
        assert (await (await client_as(role)).post("/api/v1/forget", json=body)).status_code == 403
    admin = await client_as(Role.admin)
    assert (await admin.post("/api/v1/forget", json={})).status_code == 400
    response = await admin.post("/api/v1/forget", json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["runs"] == 1 and data["traces"] == 1 and data["nothing_matched"] is False
    assert SECRET_TEXT not in (await _state(seeded["run"]))["payload"]
    repeat = (await admin.post("/api/v1/forget", json=body)).json()
    assert repeat["traces"] == 0 and repeat["scenario_versions"] == 0


# --- Signed ORBIT webhook ---------------------------------------------------------------------------


def _signed(secret: str, payload: dict) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Orbit-Signature": signature, "Content-Type": "application/json"}


async def test_orbit_webhook_requires_a_valid_signature(client, monkeypatch) -> None:
    payload = {"type": "document.forgotten", "target_type": "document", "target_id": str(uuid.uuid4())}
    body, headers = _signed("whsec_test", payload)
    monkeypatch.setattr(settings, "orbit_webhook_secret", "")
    assert (await client.post("/api/v1/webhooks/orbit", content=body, headers=headers)).status_code == 503
    monkeypatch.setattr(settings, "orbit_webhook_secret", "whsec_test")
    assert (await client.post("/api/v1/webhooks/orbit", content=body)).status_code == 401
    bad = {**headers, "X-Orbit-Signature": "sha256=" + "0" * 64}
    assert (await client.post("/api/v1/webhooks/orbit", content=body, headers=bad)).status_code == 401
    tampered = body.replace(b"document", b"memory.x")
    assert (await client.post("/api/v1/webhooks/orbit", content=tampered, headers=headers)).status_code == 401
    assert (await client.post("/api/v1/webhooks/orbit", content=body, headers=headers)).status_code == 200


async def test_orbit_forgotten_events_trigger_the_forget(client, db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "orbit_webhook_secret", "whsec_test")
    document_id, memory_id, lineage = (str(uuid.uuid4()) for _ in range(3))
    by_document = await _seed(db_session, documents=[_doc(document_id)])
    by_memory = await _seed(
        db_session, documents=[_doc("m", memory_item_id=memory_id, key=f"memory:{lineage}")]
    )
    body, headers = _signed("whsec_test", {"type": "document.forgotten", "target_id": document_id})
    first = await client.post("/api/v1/webhooks/orbit", content=body, headers=headers)
    assert (
        first.status_code == 200 and first.json()["handled"] is True and first.json()["receipt"]["runs"] == 1
    )
    body, headers = _signed(
        "whsec_test", {"type": "memory.forgotten", "target_id": memory_id, "data": {"lineage_id": lineage}}
    )
    assert (await client.post("/api/v1/webhooks/orbit", content=body, headers=headers)).json()[
        "handled"
    ] is True
    for seeded in (by_document, by_memory):
        assert SECRET_TEXT not in (await _state(seeded["run"]))["payload"]
    body, headers = _signed("whsec_test", {"type": "document.ingested", "target_id": document_id})
    ignored = (await client.post("/api/v1/webhooks/orbit", content=body, headers=headers)).json()
    assert ignored == {"handled": False, "event": "document.ingested", "receipt": None}


# --- Scheduled retention ----------------------------------------------------------------------------


@pytest.fixture
def rules(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, days in (("trace", 30), ("evaluation", 30), ("judge_cache", 30), ("feedback", 30)):
        monkeypatch.setattr(settings, f"retention_{name}_days", days)


async def test_purge_empties_old_texts_only_and_keeps_measurements(db_session, rules) -> None:
    old = await _seed(db_session, documents=[_doc(str(uuid.uuid4()))], finished_days_ago=45)
    recent = await _seed(db_session, documents=[_doc(str(uuid.uuid4()))], finished_days_ago=2)
    recent_before = (await _state(recent["run"], manifest=False))["payload"]
    async with get_sessionmaker()() as session:
        report = await retention.purge(session)
        await session.commit()
    assert report.traces >= 1 and report.trace_events >= 1 and report.evaluations >= 1
    assert report.judge_cache >= 1 and report.feedback_reports >= 1 and not report.skipped
    state = await _state(old["run"], manifest=False)
    assert SECRET_TEXT not in state["payload"] and state["evaluation"].raw_response is None
    _assert_measurements_kept(state)
    assert (await _state(recent["run"], manifest=False))["payload"] == recent_before
    async with get_sessionmaker()() as session:
        scenario = await session.get(ScenarioVersion, old["sv"])
        assert scenario.context["documents"][0]["content"] == SECRET_TEXT  # scenarios are not on a schedule
        assert (
            await session.scalar(select(AuditEvent).where(AuditEvent.action == "retention.purge")) is not None
        )
        again = await retention.purge(session)
        assert again.traces == again.trace_events == again.evaluations == again.feedback_reports == 0


async def test_dry_run_counts_without_touching_anything(db_session, rules) -> None:
    old = await _seed(db_session, documents=[_doc(str(uuid.uuid4()))], finished_days_ago=60)
    before = (await _state(old["run"], manifest=False))["payload"]
    async with get_sessionmaker()() as session:
        report = await retention.purge(session, dry_run=True)
        await session.commit()
    assert report.dry_run and report.traces >= 1 and report.evaluations >= 1 and report.judge_cache >= 1
    assert report.feedback_reports >= 1
    assert (await _state(old["run"], manifest=False))["payload"] == before
    async with get_sessionmaker()() as session:
        assert await session.scalar(select(func.count()).select_from(JudgeCacheEntry)) >= 1


async def test_a_zero_retention_keeps_that_kind_forever(db_session, monkeypatch) -> None:
    for name in ("trace", "evaluation", "judge_cache", "feedback"):
        monkeypatch.setattr(settings, f"retention_{name}_days", 0)
    old = await _seed(db_session, documents=[_doc(str(uuid.uuid4()))], finished_days_ago=4000)
    before = (await _state(old["run"], manifest=False))["payload"]
    async with get_sessionmaker()() as session:
        report = await retention.purge(session)
        await session.commit()
    assert report.total() == 0 and (await _state(old["run"], manifest=False))["payload"] == before


async def test_only_one_purge_runs_at_a_time(rules) -> None:
    async with get_sessionmaker()() as holder:
        await holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": retention.PURGE_LOCK_KEY})
        try:
            async with get_sessionmaker()() as session:
                report = await retention.purge(session)
            assert report.skipped is True and report.total() == 0
        finally:
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": retention.PURGE_LOCK_KEY})
            await holder.commit()


async def test_worker_and_cli_run_the_same_purge(db_session, rules, capsys) -> None:
    from forge.ops.__main__ import retention_pass
    from forge.workers.worker import Worker

    old = await _seed(db_session, documents=[_doc(str(uuid.uuid4()))], finished_days_ago=90)
    assert await retention_pass(True) == 0
    assert "seraient purgés" in capsys.readouterr().out
    assert SECRET_TEXT in (await _state(old["run"], manifest=False))["payload"]
    await Worker(queues=["evaluation"], concurrency=1, worker_id="test-retention").run_retention_once()
    assert SECRET_TEXT not in (await _state(old["run"], manifest=False))["payload"]
