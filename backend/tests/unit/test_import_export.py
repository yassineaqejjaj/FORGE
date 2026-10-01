"""Scenario bundles forge.scenarios/v1: parsing, error collection, round-trip, dependency order."""

from __future__ import annotations

import json

import pytest

from forge.domain.enums import ScenarioVisibility
from forge.domain.scenarios.import_export import (
    BUNDLE_FORMAT,
    Bundle,
    BundleFormatError,
    BundleScenario,
    BundleVersion,
    dump_bundle,
    load_document,
    order_by_dependencies,
    parse_bundle,
)


def _bundle() -> Bundle:
    content = {
        "description": "PRD",
        "difficulty": "hard",
        "input": {"prompt": "Rédige un PRD « export CSV »\nsur deux lignes"},
        "context": {"documents": [{"id": "D1", "title": "Spec", "content": "yes"}]},
        "constraints": ["no", "on", "2024-01-01", "1.0"],
        "expected_output": {"sections": ["Objectifs"], "score": 1.5, "flag": True, "none": None},
        "expected_behavior": "",
        "criteria": [{"key": "quality.accuracy", "weight": 2}],
        "rules": [{"id": "R1", "type": "contains", "params": {"keywords": ["PRD"]}}],
        "tool_mocks": [],
        "dataset_id": None,
    }
    return Bundle(
        exported_at="2026-09-30T10:00:00+00:00",
        scenarios=[
            BundleScenario(
                slug="scenario_prd_001",
                name="PRD export",
                category="product_management",
                versions=[
                    BundleVersion(content=content, version=1, changelog="v1", content_hash="sha256:abc")
                ],
                visibility=ScenarioVisibility.private,
                classification=2,
                tags=["prd"],
                fresh_until=None,
            ),
            BundleScenario(
                slug="scenario_prd_001_variant_short",
                name="PRD export (court)",
                category="product_management",
                versions=[BundleVersion(content={**content, "constraints": []}, version=1)],
                parent_slug="scenario_prd_001",
                variant_label="short",
            ),
        ],
    )


@pytest.mark.parametrize("fmt", ["yaml", "json"])
def test_round_trip(fmt: str) -> None:
    bundle = _bundle()
    text = dump_bundle(bundle, fmt)  # type: ignore[arg-type]
    parsed = parse_bundle(text)
    assert parsed.errors == []
    assert parsed.as_dict() == bundle.as_dict()
    assert dump_bundle(parsed, fmt) == text  # type: ignore[arg-type]


def test_yaml_strings_that_look_like_scalars_stay_strings() -> None:
    parsed = parse_bundle(dump_bundle(_bundle(), "yaml"))
    assert parsed.scenarios[0].versions[0].content["constraints"] == ["no", "on", "2024-01-01", "1.0"]


def test_yaml_dates_written_by_hand_become_iso_strings() -> None:
    doc = load_document("a: 2024-01-01\nb: [2024-01-02T10:00:00]\n")
    assert doc == {"a": "2024-01-01", "b": ["2024-01-02T10:00:00"]}


def test_entry_errors_are_collected_independently() -> None:
    data = {
        "format": BUNDLE_FORMAT,
        "scenarios": [
            {"slug": "ok_scenario", "name": "OK", "category": "analysis", "versions": [{"content": {}}]},
            {"slug": "Bad Slug", "name": "x", "category": "y", "versions": [{"content": {}}]},
            {"slug": "no_versions", "name": "x", "category": "y", "versions": []},
            {"slug": "ok_scenario", "name": "dup", "category": "y", "versions": [{"content": {}}]},
            {
                "slug": "bad_vis",
                "name": "x",
                "category": "y",
                "visibility": "secret",
                "versions": [{"content": {}}],
            },
            "not an object",
        ],
    }
    parsed = parse_bundle(json.dumps(data))
    assert [s.slug for s in parsed.scenarios] == ["ok_scenario"]
    assert len(parsed.errors) == 5
    assert {e.index for e in parsed.errors} == {1, 2, 3, 4, 5}


@pytest.mark.parametrize(
    "text",
    [
        "",
        "just a string",
        '{"format": "other/v1", "scenarios": []}',
        '{"format": "forge.scenarios/v1"}',
        "a: [unclosed",
    ],
)
def test_unusable_documents_raise(text: str) -> None:
    with pytest.raises(BundleFormatError):
        parse_bundle(text)


def test_parents_are_ordered_before_variants() -> None:
    bundle = _bundle()
    reversed_entries = list(reversed(bundle.scenarios))
    ordered = order_by_dependencies(reversed_entries)
    assert [e.slug for e in ordered] == ["scenario_prd_001", "scenario_prd_001_variant_short"]


def test_canary_is_optional_metadata() -> None:
    bundle = _bundle()
    bundle.scenarios[0].versions[0].canary = "FORGE-CANARY-abc"
    parsed = parse_bundle(dump_bundle(bundle, "json"))
    assert parsed.scenarios[0].versions[0].canary == "FORGE-CANARY-abc"
