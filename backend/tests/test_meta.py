"""GET /meta: vocabularies with French labels, rule types, adapters, capabilities, OTLP URL."""

from __future__ import annotations

from forge.domain.enums import Dimension, Role, RuleType


async def test_meta_for_viewer(client_as) -> None:
    viewer = await client_as(Role.viewer)
    response = await viewer.get("/api/v1/meta")
    assert response.status_code == 200, response.text
    meta = response.json()
    enums = meta["enums"]
    for key in (
        "roles", "adapter_kinds", "visibility", "difficulty", "run_statuses", "dimensions", "severities",
        "evaluator_kinds", "aggregation_methods", "judge_providers", "gate_actions", "verdicts", "recommendations",
        "calibration_statuses", "recommendation_categories",
    ):  # fmt: skip
        assert enums[key], key
    assert {o["value"]: o["label"] for o in enums["dimensions"]}["quality"] == "Qualité"
    assert len(enums["dimensions"]) == len(Dimension)
    assert {o["value"]: o["label"] for o in enums["roles"]}["maintainer"] == "Mainteneur"
    assert {r["type"] for r in meta["rule_types"]} == {t.value for t in RuleType}
    contains = next(r for r in meta["rule_types"] if r["type"] == "contains")
    assert contains["params_schema"]["required"] == ["keywords"] and contains["default_criterion"]
    assert {a["kind"] for a in meta["adapters"]} == {"openai", "anthropic", "nova", "custom_api", "mock"}
    assert all(a["adapter_config"] and a["example"] for a in meta["adapters"])
    assert any(c["value"] == "product_management" for c in meta["categories"])
    assert any(c["key"] == "quality.accuracy" and c["judged"] for c in meta["criteria"])
    assert any(c["key"] == "latency.total" and not c["judged"] for c in meta["criteria"])
    assert any(e["code"] == "HALLUCINATION" for e in meta["error_types"])
    assert meta["otlp_endpoint"].endswith("/v1/traces")
    assert set(meta["capabilities"]) == {"llm_judges_configured", "feedback_llm", "orbit_configured"}
    assert meta["capabilities"]["llm_judges_configured"] is False  # no provider key in tests
    assert meta["classifications"][0]["label"].startswith("C0")


async def test_meta_requires_authentication(client) -> None:
    assert (await client.get("/api/v1/meta")).status_code == 401
