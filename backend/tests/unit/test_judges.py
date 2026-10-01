"""Judges: prompt rendering, trace compaction, lenient parsing, heuristic judge, runner, cache keys."""

from __future__ import annotations

import json
from typing import Any

import pytest

from forge.domain.defaults import CRITERIA_BY_KEY
from forge.domain.enums import Dimension, EventStatus, JudgeProvider, TraceEventType
from forge.domain.judge_defaults import DEFAULT_RUBRIC_TEMPLATE
from forge.domain.judges import (
    compact_trace,
    criteria_for_judge,
    judge_cache_key,
    judged_criteria,
    parse_judge_output,
    render_prompt,
    run_judge,
    self_preference_warning,
    trace_digest,
)
from forge.domain.judges.heuristic import MAX_CONFIDENCE, heuristic_response
from forge.domain.judges.prompting import PLACEHOLDERS, substitute, unknown_placeholders
from forge.domain.ports import LLMResponse
from forge.domain.types import CriterionSpec, JudgeSpec, ModelSpec, ScoreConfig
from tests.unit.test_rules import event, make_ctx

LABELS = {
    "HALLUCINATION": "Hallucination",
    "MISSING_INFORMATION": "Information manquante",
    "BAD_REASONING": "Raisonnement",
}
CRITERIA = [CRITERIA_BY_KEY["quality.accuracy"], CRITERIA_BY_KEY["quality.completeness"]]


def judge(provider: JudgeProvider = JudgeProvider.openai, **kwargs: Any) -> JudgeSpec:
    return JudgeSpec(
        judge_id="11111111-1111-1111-1111-111111111111", key="j", version=2, name="Juge", provider=provider,
        model=kwargs.pop("model", "gpt-5-mini"), **kwargs,
    )  # fmt: skip


def answer(*items: dict[str, Any]) -> str:
    return json.dumps({"criteria": list(items), "summary": "ok"})


def item(key: str, score: Any = 4, **extra: Any) -> dict[str, Any]:
    return {"key": key, "score": score, "justification": "Justifié par le texte.", "confidence": 0.8, **extra}


# --- Prompting -------------------------------------------------------------------------------------


def test_render_prompt_substitutes_every_placeholder() -> None:
    ctx = make_ctx(
        "Ma réponse",
        expected="Un PRD complet",
        constraints=["Moins de 500 mots"],
        context={"documents": [{"id": "doc-1", "title": "Étude", "content": "Contenu de l'étude"}]},
        events=[event(1, TraceEventType.llm_call, "appel", attributes={"model": "m", "input_tokens": 10})],
    )
    prompt = render_prompt(judge(), ctx, CRITERIA, LABELS)
    for name in PLACEHOLDERS:
        assert "{" + name + "}" not in prompt.user
    assert "Ma réponse" in prompt.user and "Un PRD complet" in prompt.user
    assert "[doc-1] Étude" in prompt.user and "1. Moins de 500 mots" in prompt.user
    assert "[E1] +100ms llm_call appel" in prompt.user
    assert "`quality.accuracy`, `quality.completeness`" in prompt.user  # response block always appended
    assert prompt.prompt_hash.startswith("sha256:")
    assert render_prompt(judge(), ctx, CRITERIA, LABELS).prompt_hash == prompt.prompt_hash


def test_template_braces_and_unknown_placeholders() -> None:
    assert substitute('{"a": 1} {{x}} {output}', {"output": "OUT"}) == '{"a": 1} {x} OUT'
    assert unknown_placeholders("{output} {nope} {{literal}}") == ["nope"]
    assert unknown_placeholders(DEFAULT_RUBRIC_TEMPLATE) == []


def test_compact_trace_is_bounded() -> None:
    events = [
        event(i, TraceEventType.tool_call, f"outil-{i}", attributes={"arguments": {"q": "x" * 500}})
        for i in range(1, 300)
    ]
    events.append(event(300, TraceEventType.error, "boom", status=EventStatus.error, output="échec"))
    text = compact_trace(events, max_chars=3000)
    assert len(text) <= 3200
    assert text.startswith("[E1]") and "[E300]" in text and "omise" in text
    assert "ERREUR" in text.splitlines()[-1]
    assert compact_trace([]) == "(aucune étape enregistrée)"


# --- Parsing ---------------------------------------------------------------------------------------


def parse(text: Any, events=(), criteria=CRITERIA):
    return parse_judge_output(
        text,
        judge=judge(),
        criteria=criteria,
        events=list(events),
        known_error_types=LABELS,
        prompt_hash="sha256:p",
    )


def test_parse_valid_answer_in_fence() -> None:
    result = parse(
        "Voici :\n```json\n" + answer(item("quality.accuracy"), item("quality.completeness", 3)) + "\n```"
    )
    assert [r.criterion_key for r in result.results] == ["quality.accuracy", "quality.completeness"]
    r = result.results[0]
    assert r.evaluator_key == "j@v2" and r.judge_version == 2 and r.prompt_hash == "sha256:p"
    assert r.normalized == pytest.approx(0.8) and not result.missing


def test_parse_clamps_scores_and_confidence() -> None:
    result = parse(answer(item("quality.accuracy", 9, confidence=80), item("quality.completeness", "-2")))
    assert result.results[0].raw_score == 5 and result.results[0].confidence == pytest.approx(0.8)
    assert result.results[1].raw_score == 0
    assert any("hors échelle" in p for p in result.problems)


def test_parse_rejects_empty_justification_and_missing_criteria() -> None:
    result = parse(answer(item("quality.accuracy", justification="  ")))
    assert result.results == []
    assert result.rejected == {"quality.accuracy": "justification vide"}
    assert result.missing == ["quality.accuracy", "quality.completeness"]
    assert result.blocking_problems()


def test_parse_maps_events_and_unknown_error_types() -> None:
    events = [event(3, TraceEventType.tool_call, "search")]
    result = parse(
        answer(
            item(
                "quality.accuracy",
                evidence=[{"excerpt": "extrait", "event": "E3"}, {"excerpt": "x", "event": 99}, "[E3]"],
                errors=[
                    {"type": "MADE_UP", "severity": "high", "description": "invention", "event": 3},
                    {"type": "hallucination", "severity": "weird", "description": "d"},
                ],
            )
        ),
        events=events,
    )
    r = result.results[0]
    assert r.evidence[0].trace_event_seq == 3 and r.evidence[0].trace_event_id == events[0].id
    assert r.evidence[1].trace_event_seq is None  # unknown step dropped, excerpt kept
    assert r.evidence[2].trace_event_seq == 3
    assert r.errors[0].type == "BAD_REASONING" and "MADE_UP" in r.errors[0].description
    assert r.errors[0].evidence[0].trace_event_seq == 3
    assert r.errors[1].type == "HALLUCINATION" and r.errors[1].severity.value == "high"


def test_parse_lenient_shapes() -> None:
    keyed = parse(
        json.dumps(
            {"criteria": {"quality.accuracy": {"score": "4/5", "justification": "ok", "confidence": 1}}}
        )
    )
    assert keyed.results[0].raw_score == 4
    top_level = parse(json.dumps({"quality.accuracy": {"score": 2, "explanation": "court"}}))
    assert top_level.results[0].confidence == 0.5 and top_level.results[0].explanation == "court"
    assert parse("pas de JSON").data is None
    extra = parse(answer(item("quality.accuracy"), item("other.key")))
    assert any("non demandé" in p for p in extra.problems)


# --- Heuristic judge ---------------------------------------------------------------------------------


def test_heuristic_is_deterministic_and_capped() -> None:
    ctx = make_ctx(
        "# Objectifs\nExport CSV des rapports mensuels car les clients le demandent [doc-1].\n- format UTF-8",
        expected="Objectifs export CSV rapports mensuels UTF-8",
        context={"documents": [{"id": "doc-1", "title": "Demandes"}]},
    )
    criteria = [
        CRITERIA_BY_KEY[k]
        for k in ("quality.accuracy", "quality.completeness", "quality.sourcing", "ux.clarity")
    ]
    first = heuristic_response(ctx, criteria)
    assert first == heuristic_response(ctx, criteria)
    for entry in first["criteria"]:
        assert 0 <= entry["score"] <= 5 and entry["confidence"] <= MAX_CONFIDENCE
        assert entry["justification"].startswith("Heuristique")
    assert first["criteria"][1]["score"] >= 4  # good coverage of the expected output


def test_heuristic_flags_missing_information_and_contradictions() -> None:
    ctx = make_ctx(
        "Le module export est disponible pour tous les clients. Le module export n'est pas disponible pour tous les clients.",
        expected="Planning, budget, risques, indicateurs, dépendances, jalons",
    )
    response = heuristic_response(
        ctx, [CRITERIA_BY_KEY["quality.completeness"], CRITERIA_BY_KEY["coherence.consistency"]]
    )
    completeness, consistency = response["criteria"]
    assert completeness["errors"][0]["type"] == "MISSING_INFORMATION"
    assert consistency["errors"][0]["type"] == "CONTRADICTION"


def test_heuristic_empty_output_scores_zero() -> None:
    response = heuristic_response(make_ctx("", run_error="HTTP 500"), CRITERIA)
    assert all(c["score"] == 0 for c in response["criteria"])


def test_heuristic_unknown_criterion_uses_generic_signal() -> None:
    custom = CriterionSpec(key="ux.tone", dimension=Dimension.ux, name="Ton")
    response = heuristic_response(make_ctx("Bonjour, voici la réponse."), [custom])
    assert "signal générique" in response["criteria"][0]["justification"]


# --- Runner ----------------------------------------------------------------------------------------


class FakeClient:
    def __init__(self, *texts: str | Exception) -> None:
        self.texts = list(texts)
        self.calls: list[dict[str, Any]] = []

    async def complete(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        text = self.texts.pop(0)
        if isinstance(text, Exception):
            raise text
        return LLMResponse(
            text=text, model="gpt-5-mini-2025", input_tokens=1000, output_tokens=200, latency_ms=50
        )


async def test_runner_heuristic() -> None:
    result = await run_judge(
        judge(JudgeProvider.heuristic, model="heuristic-v1"),
        make_ctx("Réponse"),
        CRITERIA,
        error_types=LABELS,
    )
    assert result.status == "ok" and len(result.results) == 2 and result.cost == 0


async def test_runner_retries_once_with_correction() -> None:
    client = FakeClient("pas du json", answer(item("quality.accuracy"), item("quality.completeness")))
    result = await run_judge(
        judge(), make_ctx("x"), CRITERIA, error_types=LABELS, client=client, cost_fn=lambda m, i, o: 0.002
    )
    assert result.status == "ok" and result.attempts == 2
    assert client.calls[1]["messages"][-1]["role"] == "user"
    assert "n'est pas exploitable" in client.calls[1]["messages"][-1]["content"]
    assert result.input_tokens == 2000 and result.cost == 0.002
    assert sum(r.cost or 0 for r in result.results) == pytest.approx(0.002)
    assert result.results[0].model == "gpt-5-mini-2025"


async def test_runner_merges_partial_answers_and_never_invents() -> None:
    client = FakeClient(answer(item("quality.accuracy")), answer(item("quality.accuracy", 1)))
    result = await run_judge(judge(), make_ctx("x"), CRITERIA, error_types=LABELS, client=client)
    assert result.status == "partial"
    assert [r.criterion_key for r in result.results] == ["quality.accuracy"]
    assert result.results[0].raw_score == 4  # first verdict kept
    assert result.parsed.missing == ["quality.completeness"]


async def test_runner_failure_is_reported_not_raised() -> None:
    client = FakeClient(RuntimeError("HTTP 500"))
    result = await run_judge(judge(), make_ctx("x"), CRITERIA, error_types=LABELS, client=client)
    assert result.status == "failed" and "HTTP 500" in (result.error or "")
    no_client = await run_judge(judge(), make_ctx("x"), CRITERIA, error_types=LABELS)
    assert no_client.status == "failed"


# --- Selection, bias, cache ------------------------------------------------------------------------


def test_judged_criteria_excludes_metric_dimensions() -> None:
    ctx = make_ctx("x")
    config = ScoreConfig(
        config_id="c", key="c", version=1, name="c", dimension_weights={},
        criteria=[CRITERIA_BY_KEY["cost.tokens"], CRITERIA_BY_KEY["ux.perceived_usefulness"]],
    )  # fmt: skip
    keys = [c.key for c in judged_criteria(ctx.scenario, config, CRITERIA_BY_KEY)]
    assert "cost.tokens" not in keys and keys[-1] == "ux.perceived_usefulness"
    assert keys[0] == "quality.accuracy"
    only = criteria_for_judge(
        judge(criteria=["ux.clarity"]), judged_criteria(ctx.scenario, config, CRITERIA_BY_KEY)
    )
    assert [c.key for c in only] == ["ux.clarity"]


def test_self_preference_warning() -> None:
    ctx = make_ctx("x")
    ctx.agent.model = ModelSpec(provider="openai", model="gpt-4.1")
    assert self_preference_warning(judge(), ctx.agent)
    assert self_preference_warning(judge(JudgeProvider.anthropic, model="claude-opus-5-5"), ctx.agent) is None


def test_cache_key_depends_on_inputs() -> None:
    events = [event(1, TraceEventType.message, "m", output="a")]
    base = {
        "judge_content_hash": "sha256:j", "scenario_content_hash": "sha256:s", "output_text": "out",
        "output_json": None, "trace_digest": trace_digest(events), "criteria_keys": ["a", "b"],
    }  # fmt: skip
    key = judge_cache_key(**base)
    assert key == judge_cache_key(**base)
    assert key != judge_cache_key(**{**base, "output_text": "autre"})
    assert key != judge_cache_key(**{**base, "criteria_keys": ["a"]})
    other = [event(1, TraceEventType.message, "m", output="b")]
    assert trace_digest(events) != trace_digest(other)
