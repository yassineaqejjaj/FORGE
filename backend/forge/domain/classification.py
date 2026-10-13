"""Classification of the context handed to an agent (same C0–C3 policy as ORBIT, fail-closed).

A document carries the classification ORBIT gave it. A document without one inherits the scenario's; a
value that is not a valid level counts as C3, never as lower: an unreadable label must not weaken a
control. ``context_level`` is the highest level present, used wherever a copy of the context is made or
sent out (NOVA payload, promotion of a run to a scenario, published learnings).
"""

from __future__ import annotations

from typing import Any

from forge.domain.enums import Classification

MAX_LEVEL = int(Classification.C3)


def parse_level(value: Any) -> int | None:
    """``0``–``3`` (also ``"2"`` / ``"C2"``), else ``None``."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip().upper().removeprefix("C")
        value = int(text) if text.isdigit() else None
    if isinstance(value, int) and 0 <= value <= MAX_LEVEL:
        return value
    return None


def document_level(document: dict[str, Any], fallback: int) -> int:
    """Level of one document: its own, else ``fallback`` (the scenario's), C3 when unreadable."""
    raw = fallback if document.get("classification") is None else document["classification"]
    level = parse_level(raw)
    return level if level is not None else MAX_LEVEL


def context_level(context: dict[str, Any] | None, fallback: int) -> int:
    """Highest level among the documents of ``context`` and ``fallback``."""
    base = document_level({}, fallback)
    documents = [d for d in (context or {}).get("documents") or [] if isinstance(d, dict)]
    return max([base, *(document_level(d, base) for d in documents)])


def with_levels(context: dict[str, Any], fallback: int) -> dict[str, Any]:
    """Copy of ``context``: every document gets a valid ``classification``, plus ``max_classification``."""
    base = document_level({}, fallback)
    documents = [
        {**d, "classification": document_level(d, base)} if isinstance(d, dict) else d
        for d in context.get("documents") or []
    ]
    result = {**context, "max_classification": context_level(context, base)}
    if "documents" in context:
        result["documents"] = documents
    return result
