"""Benchmark contamination checks: canaries and long n-gram overlap with private expected outputs."""

from __future__ import annotations

from forge.domain.scenarios.contamination import (
    CanaryRef,
    PrivateOutputRef,
    ScenarioRef,
    agent_texts,
    check_contamination,
    flatten_text,
)
from forge.domain.versioning import new_canary

PRIVATE = ScenarioRef("s-1", "scenario_secret_001", "private")
FRESH = ScenarioRef("s-2", "scenario_fresh_001", "fresh")
EXPECTED = (
    "Le plan de migration doit commencer par un audit complet des flux existants puis prévoir une phase "
    "pilote sur deux équipes avant la généralisation progressive à toute l'organisation."
)


def test_canary_of_private_or_fresh_scenario_is_detected() -> None:
    canary, fresh_canary = new_canary(), new_canary()
    texts = agent_texts(
        system_prompt=f"Tu es un agent. {canary}",
        tools=[{"name": "search", "description": f"cherche {fresh_canary}"}],
        adapter_config={},
    )
    warnings = check_contamination(
        texts, canaries=[CanaryRef(canary, PRIVATE), CanaryRef(fresh_canary, FRESH)]
    )
    assert {(w["type"], w["location"], w["scenario_slug"]) for w in warnings} == {
        ("canary", "system_prompt", "scenario_secret_001"),
        ("canary", "tools.search", "scenario_fresh_001"),
    }
    assert all(w["severity"] == "critical" for w in warnings)
    assert all(canary not in w["message"] for w in warnings)


def test_unknown_canary_is_ignored() -> None:
    texts = {"system_prompt": new_canary()}
    assert check_contamination(texts, canaries=[CanaryRef(new_canary(), PRIVATE)]) == []


def test_long_overlap_with_private_expected_output_is_detected_without_excerpt() -> None:
    prompt = "Consignes : " + EXPECTED.upper().replace("É", "E") + " Merci."
    warnings = check_contamination(
        {"system_prompt": prompt}, private_outputs=[PrivateOutputRef(EXPECTED, PRIVATE)]
    )
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning["type"] == "ngram_overlap" and warning["overlap_words"] >= 25
    assert "audit complet" not in str(warning).lower()


def test_short_overlap_is_not_reported() -> None:
    eleven_words = " ".join(EXPECTED.split()[:11])
    assert (
        check_contamination(
            {"system_prompt": eleven_words}, private_outputs=[PrivateOutputRef(EXPECTED, PRIVATE)]
        )
        == []
    )
    twelve_words = " ".join(EXPECTED.split()[:12])
    assert (
        len(check_contamination({"p": twelve_words}, private_outputs=[PrivateOutputRef(EXPECTED, PRIVATE)]))
        == 1
    )


def test_duplicate_outputs_are_reported_once_per_location() -> None:
    outputs = [PrivateOutputRef(EXPECTED, PRIVATE), PrivateOutputRef(EXPECTED + " Fin.", PRIVATE)]
    warnings = check_contamination({"system_prompt": EXPECTED}, private_outputs=outputs)
    assert len(warnings) == 1


def test_structured_outputs_and_adapter_config_are_flattened() -> None:
    assert "deux" in flatten_text({"a": ["un", {"b": "deux"}], "n": 3})
    texts = agent_texts(system_prompt="", tools=[], adapter_config={"body_template": {"system": EXPECTED}})
    assert set(texts) == {"adapter_config"}
    assert check_contamination(texts, private_outputs=[PrivateOutputRef(EXPECTED, PRIVATE)])
