"""Feedback builder (docs §7.7): strengths, weaknesses, grouped errors, mapped recommendations."""

from __future__ import annotations

import json

import httpx
import respx

from forge.domain.enums import Dimension, ErrorSeverity, Priority, RecommendationCategory
from forge.domain.feedback import (
    FeedbackCriterion,
    FeedbackError,
    FeedbackInput,
    build_feedback,
    build_group_feedback,
)
from forge.domain.types import EvidenceRef, to_dict


def crit(key: str, value: float) -> FeedbackCriterion:
    return FeedbackCriterion(
        key=key, value=value, name=key.split(".")[1], dimension=Dimension(key.split(".")[0])
    )


def err(type_: str, severity: str = "medium", **kwargs) -> FeedbackError:
    return FeedbackError(
        type=type_, severity=ErrorSeverity(severity), description=f"{type_} détecté", **kwargs
    )


def test_strengths_weaknesses_and_summary() -> None:
    report = build_feedback(
        FeedbackInput(
            score=72.4,
            passed=True,
            criteria=[
                crit("quality.accuracy", 0.9),
                crit("ux.clarity", 0.5),
                crit("quality.usefulness", 0.7),
            ],
            errors=[],
        )
    )
    assert report.strengths == ["accuracy (quality.accuracy) : 0,90"]
    assert report.weaknesses == ["clarity (ux.clarity) : 0,50"]
    assert report.summary.startswith("Score global 72,4/100 — réussi.")
    assert report.generator == "deterministic"
    assert report.recommendations[0].category == RecommendationCategory.output_format


def test_error_mapping_rules() -> None:
    errors = [
        err("SOURCE_ERROR", "high", evidence=[EvidenceRef(excerpt="cite [9]")]),
        err("HALLUCINATION", "high"),
        err("INSTRUCTION_FAILURE"),
        err("WRONG_TOOL"),
        err("FORMAT_ERROR", "low"),
        err("MEMORY_ERROR"),
        err("DATA_LEAK", "critical"),
    ]
    report = build_feedback(FeedbackInput(score=40, errors=errors, gate_failures=["no-data-leak : fuite"]))
    categories = {r.category: r for r in report.recommendations}
    assert set(categories) >= {
        RecommendationCategory.retrieval,
        RecommendationCategory.system_prompt,
        RecommendationCategory.tools,
        RecommendationCategory.output_format,
        RecommendationCategory.memory,
        RecommendationCategory.rule,
    }
    retrieval = categories[RecommendationCategory.retrieval]
    assert set(retrieval.related_errors) == {"SOURCE_ERROR", "HALLUCINATION"}
    assert retrieval.evidence[0].excerpt == "cite [9]"
    assert report.recommendations[0].category == RecommendationCategory.rule
    assert report.recommendations[0].priority == Priority.p0
    assert report.priority_actions[0].startswith("[P0]")
    grouped = {e["type"]: e for e in report.errors}
    assert (
        grouped["DATA_LEAK"]["severity"] == "critical" and grouped["DATA_LEAK"]["label"] == "Fuite de données"
    )
    assert report.errors[0]["type"] == "DATA_LEAK"  # sorted by severity


def test_cost_and_latency_recommendations() -> None:
    report = build_feedback(
        FeedbackInput(
            score=60,
            criteria=[
                crit("cost.estimated_cost", 0.2),
                crit("latency.total", 0.3),
                crit("cost.tokens", 0.55),
            ],
        )
    )
    categories = [r.category for r in report.recommendations]
    assert RecommendationCategory.model in categories and RecommendationCategory.orchestration in categories
    model = next(r for r in report.recommendations if r.category == RecommendationCategory.model)
    assert model.related_criteria == ["cost.estimated_cost"]  # tokens at 0.55 is not alarming


def test_group_feedback_counts_across_runs() -> None:
    inputs = [
        FeedbackInput(
            score=80,
            criteria=[crit("quality.accuracy", 0.9)],
            errors=[err("HALLUCINATION", "high", run_id="r1")],
        ),
        FeedbackInput(
            score=60,
            criteria=[crit("quality.accuracy", 0.5)],
            errors=[err("HALLUCINATION", "high", run_id="r2")],
        ),
        FeedbackInput(score=None, run_failed="HTTP 500"),
    ]
    report = build_group_feedback(inputs, label="Agent v1")
    assert report.score == 70
    assert report.summary.startswith("Agent v1 — Sur 3 runs : score moyen 70,0/100.")
    assert report.errors[0]["count"] == 2 and report.errors[0]["runs"] == 2
    assert report.recommendations[0].priority == Priority.p0  # high severity in ≥ 50 % of runs
    assert "1 run(s) en échec" in report.summary


def test_report_is_json_serialisable_and_stable() -> None:
    data = FeedbackInput(score=50, criteria=[crit("ux.clarity", 0.2)], errors=[err("BAD_REASONING")])
    first, second = to_dict(build_feedback(data)), to_dict(build_feedback(data))
    assert first == second
    assert first["recommendations"][0]["category"] in {c.value for c in RecommendationCategory}


def test_empty_group() -> None:
    report = build_group_feedback([])
    assert report.score is None and report.recommendations == []


@respx.mock
async def test_optional_llm_synthesis_rewrites_text_only(monkeypatch) -> None:
    from forge.config import settings
    from forge.infra.llm import base as llm_base
    from forge.services import feedback as feedback_service

    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(llm_base, "sleep", instant)
    monkeypatch.setattr(settings, "feedback_llm_base_url", "https://fb.test/v1")
    monkeypatch.setattr(settings, "feedback_llm_model", "gpt-4.1-mini")
    report = build_feedback(
        FeedbackInput(score=40, errors=[err("HALLUCINATION", "high", evidence=[EvidenceRef(excerpt="x")])])
    )
    content = json.dumps(
        {
            "summary": "Synthèse LLM.",
            "recommendations": [{"index": 0, "title": "Titre LLM", "description": "Desc LLM"}],
        }
    )
    respx.post("https://fb.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"model": "gpt-4.1-mini", "choices": [{"message": {"content": content}}], "usage": {}}
        )
    )
    enriched = await feedback_service._llm_enrich(report)
    assert enriched.generator == "llm:gpt-4.1-mini" and enriched.summary == "Synthèse LLM."
    rec = enriched.recommendations[0]
    assert rec.title == "Titre LLM" and rec.category == RecommendationCategory.retrieval
    assert rec.evidence[0].excerpt == "x"  # evidence never comes from the LLM
    respx.post("https://fb.test/v1/chat/completions").mock(return_value=httpx.Response(500))
    fallback = await feedback_service._llm_enrich(
        build_feedback(FeedbackInput(score=40, errors=[err("HALLUCINATION")]))
    )
    assert fallback.generator == "deterministic"
