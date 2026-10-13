"""Classification of an agent context: per-document level, fail-closed fallbacks."""

from __future__ import annotations

import pytest

from forge.domain.classification import context_level, document_level, parse_level, with_levels


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (3, 3),
        ("2", 2),
        ("C1", 1),
        (4, None),
        (-1, None),
        (True, None),
        ("secret", None),
        (None, None),
    ],
)
def test_parse_level(value, expected) -> None:
    assert parse_level(value) == expected


def test_document_level_is_its_own_else_the_scenarios_else_secret() -> None:
    assert document_level({"classification": 2}, 1) == 2
    assert document_level({"classification": 0}, 3) == 0
    assert document_level({}, 2) == 2 and document_level({"classification": None}, 2) == 2
    assert document_level({"classification": "???"}, 1) == 3  # unreadable label: never lower
    assert document_level({}, 9) == 3  # unreadable scenario level too


def test_context_level_is_the_highest_present() -> None:
    context = {"documents": [{"id": "a", "classification": 1}, {"id": "b", "classification": 3}, "brut"]}
    assert context_level(context, 1) == 3
    assert context_level({"documents": [{"id": "a"}]}, 2) == 2
    assert context_level({}, 1) == 1 and context_level(None, 2) == 2


def test_with_levels_normalises_every_document_without_mutating() -> None:
    context = {
        "documents": [{"id": "a"}, {"id": "b", "classification": 2}, {"id": "c", "classification": "x"}]
    }
    result = with_levels(context, 1)
    assert [d["classification"] for d in result["documents"]] == [1, 2, 3]
    assert result["max_classification"] == 3
    assert "classification" not in context["documents"][0] and "max_classification" not in context
    assert with_levels({}, 2) == {"max_classification": 2}
