"""Rule engine: every RuleType of docs §7.2 (pure, no database)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from forge.domain.enums import (
    AdapterKind,
    Difficulty,
    Dimension,
    ErrorSeverity,
    EvaluatorKind,
    EventStatus,
    RuleType,
    ScenarioVisibility,
    TraceEventType,
)
from forge.domain.rules import (
    MISCONFIGURED_PREFIX,
    RULE_HANDLERS,
    evaluate_rule,
    evaluate_rules,
    validate_rule,
)
from forge.domain.rules.extraction import extract_json, extract_json_object
from forge.domain.rules.jsonpath import JsonPathError, get_path, is_present, parse_path
from forge.domain.types import (
    AgentBudget,
    AgentSpec,
    EvaluationContext,
    RuleSpec,
    ScenarioSpec,
    ScoreConfig,
    TokenUsage,
    TraceEventView,
)

CANARY = "FORGE-CANARY-0123456789abcdef01234567"


def make_ctx(
    output: str = "",
    *,
    output_json: Any = None,
    events: list[TraceEventView] | None = None,
    context: dict[str, Any] | None = None,
    expected: Any = None,
    constraints: list[str] | None = None,
    prompt: str = "Rédige un PRD pour l'export CSV.",
    latency_ms: float | None = 3000.0,
    cost: float | None = 0.01,
    tokens: tuple[int, int] = (1000, 500),
    max_tokens: int | None = None,
    run_error: str | None = None,
    config: ScoreConfig | None = None,
) -> EvaluationContext:
    scenario = ScenarioSpec(
        scenario_id="s1",
        scenario_version_id="sv1",
        slug="prd-export",
        name="PRD export CSV",
        version=1,
        category="product_management",
        difficulty=Difficulty.medium,
        visibility=ScenarioVisibility.public,
        input={"prompt": prompt},
        context=context or {},
        constraints=constraints or [],
        expected_output=expected,
        canary=CANARY,
        content_hash="sha256:scenario",
    )
    agent = AgentSpec(
        agent_id="a1", agent_version_id="av1", agent_name="Agent", agent_slug="agent", version="1.0",
        adapter_kind=AdapterKind.mock, budget=AgentBudget(max_tokens=max_tokens),
    )  # fmt: skip
    return EvaluationContext(
        run_id="run-1",
        scenario=scenario,
        agent=agent,
        config=config
        or ScoreConfig(config_id="c1", key="cfg", version=1, name="cfg", dimension_weights={"quality": 1}),
        output_text=output,
        output_json=output_json,
        events=events or [],
        token_usage=TokenUsage(*tokens),
        estimated_cost=cost,
        latency_ms=latency_ms,
        run_error=run_error,
    )


def event(seq: int, type_: TraceEventType, name: str, **kwargs: Any) -> TraceEventView:
    return TraceEventView(
        id=f"00000000-0000-0000-0000-{seq:012d}",
        seq=seq,
        type=type_,
        name=name,
        offset_ms=seq * 100.0,
        duration_ms=kwargs.pop("duration_ms", 10.0),
        status=kwargs.pop("status", EventStatus.ok),
        **kwargs,
    )


def rule(type_: RuleType, rule_id: str = "R1", **params: Any) -> RuleSpec:
    return RuleSpec(id=rule_id, type=type_, params=params)


def run(ctx: EvaluationContext, spec: RuleSpec):
    return evaluate_rule(ctx, spec)


def test_every_rule_type_has_a_handler() -> None:
    assert set(RULE_HANDLERS) == set(RuleType)


def test_result_shape_and_default_criterion() -> None:
    result = run(make_ctx("Bonjour"), rule(RuleType.contains, keywords=["bonjour"]))
    assert result.evaluator_kind == EvaluatorKind.rule
    assert result.evaluator_key == "R1"
    assert result.criterion_key == "coherence.constraints"
    assert result.dimension == Dimension.coherence
    assert (result.scale_min, result.scale_max) == (0.0, 1.0)
    assert result.passed is True and result.errors == []
    assert result.explanation


def test_required_fields() -> None:
    ctx = make_ctx(output_json={"a": {"b": [{"c": 1}]}, "title": "x", "empty": ""})
    ok = run(ctx, rule(RuleType.required_fields, fields=["a.b[0].c", "title"]))
    assert ok.passed and ok.raw_score == 1.0
    partial = run(ctx, rule(RuleType.required_fields, fields=["title", "missing", "empty", "a.b[1].c"]))
    assert not partial.passed
    assert partial.raw_score == pytest.approx(0.25)
    assert partial.errors[0].type == "FORMAT_ERROR"
    assert "missing" in partial.explanation


def test_required_fields_from_markdown_fence() -> None:
    ctx = make_ctx('Voici :\n```json\n{"name": "Export", "items": [1, 2]}\n```\n')
    assert run(ctx, rule(RuleType.required_fields, fields=["name", "items[1]"])).passed
    no_json = run(make_ctx("pas de json"), rule(RuleType.required_fields, fields=["x"]))
    assert not no_json.passed and no_json.raw_score == 0


def test_json_valid_and_schema() -> None:
    assert run(make_ctx('{"a": 1}'), rule(RuleType.json_valid)).passed
    assert run(
        make_ctx("```json\n[1, 2,]\n```"), rule(RuleType.json_valid)
    ).passed  # trailing comma tolerated
    bad = run(make_ctx("{oops"), rule(RuleType.json_valid))
    assert not bad.passed and bad.errors[0].type == "FORMAT_ERROR"
    schema = {
        "type": "object",
        "required": ["title", "priority"],
        "properties": {"priority": {"type": "integer"}},
    }
    good = run(make_ctx('{"title": "t", "priority": 2}'), rule(RuleType.json_schema, schema=schema))
    assert good.passed
    wrong = run(make_ctx('{"title": "t", "priority": "haute"}'), rule(RuleType.json_schema, schema=schema))
    assert not wrong.passed and "priority" in wrong.explanation


def test_regex_match_absent_and_flags() -> None:
    ctx = make_ctx("# Titre\nLigne avec TODO")
    assert run(ctx, rule(RuleType.regex_match, pattern="^# ", flags="m")).passed
    assert not run(ctx, rule(RuleType.regex_match, pattern="^Ligne$")).passed
    absent = run(ctx, rule(RuleType.regex_absent, pattern="todo", flags="i"))
    assert not absent.passed
    assert absent.errors[0].type == "POLICY_VIOLATION"
    assert absent.evidence and "TODO" in (absent.evidence[0].excerpt or "")


def test_contains_modes_and_accents() -> None:
    ctx = make_ctx("Le périmètre inclut l'export CSV.")
    all_mode = run(ctx, rule(RuleType.contains, keywords=["perimetre", "CSV", "PDF"]))
    assert not all_mode.passed and all_mode.raw_score == pytest.approx(2 / 3)
    assert all_mode.errors[0].type == "MISSING_INFORMATION"
    any_mode = run(ctx, rule(RuleType.contains, keywords=["PDF", "csv"], mode="any"))
    assert any_mode.passed and any_mode.raw_score == 1.0
    sensitive = run(ctx, rule(RuleType.contains, keywords=["csv"], case_sensitive=True))
    assert not sensitive.passed


def test_not_contains() -> None:
    ctx = make_ctx("Nous garantissons un remboursement intégral.")
    result = run(ctx, rule(RuleType.not_contains, keywords=["garantissons", "promis"]))
    assert not result.passed and result.raw_score == 0
    assert "garantissons" in result.explanation
    assert run(ctx, rule(RuleType.not_contains, keywords=["promis"])).passed


def test_sections_present() -> None:
    text = "# Objectifs\n...\n## Périmètre\n...\n**Critères d'acceptation**\n...\nRisques\n------\n"
    ctx = make_ctx(text)
    ok = run(
        ctx,
        rule(
            RuleType.sections_present,
            sections=["objectifs", "PERIMETRE", "criteres d'acceptation", "risques"],
        ),
    )
    assert ok.passed, ok.explanation
    missing = run(ctx, rule(RuleType.sections_present, sections=["Objectifs", "Planning"]))
    assert not missing.passed and missing.raw_score == 0.5


def test_citation_required() -> None:
    ctx = make_ctx("Selon [1] et [source: rapport 2024], ainsi que [doc-42].")
    assert run(ctx, rule(RuleType.citation_required, min=3)).passed
    few = run(make_ctx("Une seule [1]."), rule(RuleType.citation_required, min=2))
    assert not few.passed and few.raw_score == 0.5 and few.errors[0].type == "SOURCE_ERROR"
    custom = run(make_ctx("(Réf. A12)"), rule(RuleType.citation_required, pattern=r"\(Réf\. \w+\)"))
    assert custom.passed


def test_source_present() -> None:
    context = {"documents": [{"id": "doc-1", "title": "Étude marché"}, {"id": "doc-2", "title": "Roadmap"}]}
    ok = run(make_ctx("D'après l'étude marché…", context=context), rule(RuleType.source_present))
    assert ok.passed
    two = run(make_ctx("Voir doc-1.", context=context), rule(RuleType.source_present, min=2))
    assert not two.passed and two.raw_score == 0.5
    na = run(make_ctx("rien"), rule(RuleType.source_present))
    assert na.passed and "non applicable" in na.explanation


def test_no_pii_types_allow_and_masking() -> None:
    text = "Écrivez à jean.dupont@example.com ou support@forge.io, tél. 06 12 34 56 78."
    result = run(make_ctx(text), rule(RuleType.no_pii, allow=["support@forge.io"]))
    assert not result.passed
    assert result.errors[0].type == "DATA_LEAK"
    assert "jean.dupont@example.com" not in str(result.evidence)
    only_phone = run(make_ctx("jean@example.com"), rule(RuleType.no_pii, types=["PHONE"]))
    assert only_phone.passed
    assert run(make_ctx("Aucune donnée personnelle."), rule(RuleType.no_pii)).passed


def test_no_pii_scans_structured_output() -> None:
    result = run(make_ctx("ok", output_json={"contact": "marie@example.org"}), rule(RuleType.no_pii))
    assert not result.passed


def test_expected_value() -> None:
    ctx = make_ctx(output_json={"decision": {"go": True, "score": 4.0, "tags": ["a"]}})
    assert run(ctx, rule(RuleType.expected_value, path="decision.go", value=True)).passed
    assert run(ctx, rule(RuleType.expected_value, path="decision.score", value=4)).passed
    assert run(ctx, rule(RuleType.expected_value, path="decision.tags", value=["a"])).passed
    wrong = run(ctx, rule(RuleType.expected_value, path="decision.go", value=1))
    assert not wrong.passed  # true is not 1 in JSON terms
    missing = run(ctx, rule(RuleType.expected_value, path="decision.nope", value=1))
    assert not missing.passed and "absent" in missing.explanation


def test_length_rules() -> None:
    ctx = make_ctx("un deux trois quatre cinq six")
    over = run(ctx, rule(RuleType.max_length, words=3))
    assert not over.passed and over.raw_score == pytest.approx(0.5)
    assert run(ctx, rule(RuleType.max_length, words=10, chars=100)).passed
    under = run(ctx, rule(RuleType.min_length, words=12))
    assert not under.passed and under.raw_score == pytest.approx(0.5)
    assert under.errors[0].type == "MISSING_INFORMATION"


def test_tool_rules() -> None:
    events = [
        event(2, TraceEventType.tool_call, "search_docs", attributes={"tool": "search_docs"}),
        event(3, TraceEventType.tool_result, "search_docs"),
        event(4, TraceEventType.tool_call, "send_email"),
    ]
    ctx = make_ctx("ok", events=events)
    called = run(ctx, rule(RuleType.tool_called, tool="search_docs"))
    assert called.passed and called.evidence[0].trace_event_seq == 2
    assert not run(ctx, rule(RuleType.tool_called, tool="search_docs", min=2)).passed
    forbidden = run(ctx, rule(RuleType.tool_not_called, tool="send_email"))
    assert not forbidden.passed and forbidden.errors[0].type == "WRONG_TOOL"
    assert forbidden.errors[0].evidence[0].trace_event_seq == 4
    assert run(ctx, rule(RuleType.max_tool_calls, max=2)).passed
    too_many = run(ctx, rule(RuleType.max_tool_calls, max=1))
    assert not too_many.passed and too_many.raw_score == 0.5


def test_latency_and_cost_rules() -> None:
    ctx = make_ctx("ok", latency_ms=8000, cost=0.2)
    slow = run(ctx, rule(RuleType.max_latency, ms=4000))
    assert not slow.passed and slow.raw_score == 0.5 and slow.errors[0].type == "TIMEOUT"
    assert slow.criterion_key == "latency.total" and slow.dimension == Dimension.latency
    expensive = run(ctx, rule(RuleType.max_cost, max=0.1))
    assert not expensive.passed and expensive.errors[0].type == "BUDGET_EXCEEDED"
    unknown = run(make_ctx("ok", cost=None), rule(RuleType.max_cost, max=0.1))
    assert unknown.passed


def test_no_canary_is_critical_contamination() -> None:
    result = run(make_ctx(f"Le code {CANARY} apparaît"), rule(RuleType.no_canary))
    assert not result.passed
    error = result.errors[0]
    assert error.type == "CONTAMINATION" and error.severity == ErrorSeverity.critical
    assert CANARY not in str(result.evidence)  # canary only visible to maintainers
    assert "ce scénario" in result.explanation
    assert run(make_ctx("propre"), rule(RuleType.no_canary)).passed


def test_overrides_and_descriptions() -> None:
    spec = RuleSpec(
        id="brand", type=RuleType.contains, params={"keywords": ["FORGE"]}, description="Nommer le produit",
        criterion_key="quality.completeness", severity=ErrorSeverity.high, error_type="INSTRUCTION_FAILURE",
    )  # fmt: skip
    result = run(make_ctx("rien"), spec)
    assert result.criterion_key == "quality.completeness"
    assert result.explanation.startswith("Nommer le produit")
    assert result.errors[0].type == "INSTRUCTION_FAILURE" and result.errors[0].severity == ErrorSeverity.high


def test_misconfigured_rule_reports_without_error() -> None:
    result = run(make_ctx("x"), rule(RuleType.regex_match, pattern="("))
    assert result.passed is False and result.errors == []
    assert result.explanation.startswith(MISCONFIGURED_PREFIX)


def test_validate_rule_messages() -> None:
    assert validate_rule(rule(RuleType.regex_match, pattern="(")) != []
    assert validate_rule(rule(RuleType.contains)) == ["paramètre « keywords » requis"]
    assert validate_rule(rule(RuleType.json_schema, schema={"type": "nope"})) != []
    assert validate_rule(rule(RuleType.max_length)) != []
    assert validate_rule(rule(RuleType.no_canary)) == []
    assert validate_rule(rule(RuleType.contains, keywords=["a"])) == []
    assert validate_rule(rule(RuleType.no_pii, types=["EMAIL", "PHONE"])) == []
    assert validate_rule(rule(RuleType.no_pii, types=["SSN"])) != []


def test_duplicate_rule_ids_are_made_unique() -> None:
    results = evaluate_rules(make_ctx("a"), [rule(RuleType.json_valid), rule(RuleType.no_canary)])
    assert [r.evaluator_key for r in results] == ["R1", "R1#2"]


def test_failed_execution_explanation() -> None:
    result = run(make_ctx("", run_error="HTTP 500"), rule(RuleType.contains, keywords=["x"]))
    assert "exécution en échec" in result.explanation


# --- helpers --------------------------------------------------------------------------------------


def test_json_path_parsing() -> None:
    assert parse_path("a.b[0].c") == ["a", "b", 0, "c"]
    assert parse_path('$.items[*]["key.with.dots"]')[0] == "items"
    with pytest.raises(JsonPathError):
        parse_path("")
    data = {"items": [{"id": 1}, {"id": 2}], "x": None}
    assert get_path(data, "items[*].id").value == [1, 2]
    assert get_path(data, "items[-1].id").value == 2
    assert get_path(data, "x").found and not is_present(data, "x")
    assert not get_path(data, "items[5]").found


def test_json_extraction() -> None:
    assert extract_json('{"a": 1}').source == "text"
    assert extract_json('bla ```json\n{"a": 1}\n``` bla').source == "fence"
    embedded = extract_json('Résultat : {"a": {"b": "}"}} fin')
    assert embedded.ok and embedded.value == {"a": {"b": "}"}}
    assert not extract_json("").ok
    assert extract_json("x", native={"n": 1}).source == "native"
    assert extract_json_object('[{"key": "k", "score": 1}]') == {"criteria": [{"key": "k", "score": 1}]}


def test_event_helper_timestamps() -> None:  # sanity for the helpers used across unit tests
    assert make_ctx().events == [] and datetime.now(UTC).year >= 2025
