"""Minimal JSON path helper used by rules (``a.b[0].c``, ``items[*].id``, ``["key with dots"]``).

Supported syntax: dotted keys, integer indexes ``[0]`` (negative allowed), wildcard ``[*]`` (the
path then matches when *every* element has the rest of the path) and quoted keys ``["a.b"]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN = re.compile(
    r"""
    \s*(?:
        \[\s*(?P<index>-?\d+)\s*\]            # [0]
      | \[\s*(?P<star>\*)\s*\]                # [*]
      | \[\s*(?P<q>["'])(?P<quoted>.*?)(?P=q)\s*\]   # ["key"]
      | \.?(?P<key>[^.\[\]]+)                 # key  /  .key
    )
    """,
    re.VERBOSE,
)

WILDCARD = object()


class JsonPathError(ValueError):
    """Invalid path syntax (message is user-facing, French)."""


@dataclass(frozen=True, slots=True)
class PathLookup:
    found: bool
    value: Any = None


def parse_path(path: str) -> list[Any]:
    """Split ``path`` into keys (``str``), indexes (``int``) and :data:`WILDCARD` markers."""
    text = (path or "").strip()
    if text.startswith("$"):
        text = text[1:]
    if not text:
        raise JsonPathError("Chemin JSON vide")
    parts: list[Any] = []
    pos = 0
    while pos < len(text):
        if text[pos] == "." and pos + 1 < len(text) and text[pos + 1] == "[":
            pos += 1
            continue
        match = _TOKEN.match(text, pos)
        if match is None or match.end() == pos:
            raise JsonPathError(f"Chemin JSON invalide : « {path} » (position {pos})")
        if match.group("index") is not None:
            parts.append(int(match.group("index")))
        elif match.group("star"):
            parts.append(WILDCARD)
        elif match.group("quoted") is not None:
            parts.append(match.group("quoted"))
        else:
            key = match.group("key").strip()
            if not key:
                raise JsonPathError(f"Chemin JSON invalide : « {path} »")
            parts.append(key)
        pos = match.end()
    return parts


def _lookup(value: Any, parts: list[Any]) -> PathLookup:
    if not parts:
        return PathLookup(True, value)
    head, rest = parts[0], parts[1:]
    if head is WILDCARD:
        if not isinstance(value, list) or not value:
            return PathLookup(False)
        values = []
        for item in value:
            sub = _lookup(item, rest)
            if not sub.found:
                return PathLookup(False)
            values.append(sub.value)
        return PathLookup(True, values)
    if isinstance(head, int):
        if not isinstance(value, list):
            return PathLookup(False)
        try:
            return _lookup(value[head], rest)
        except IndexError:
            return PathLookup(False)
    if isinstance(value, dict):
        if head in value:
            return _lookup(value[head], rest)
        return PathLookup(False)
    if isinstance(value, list) and head.isdigit():
        return _lookup(value, [int(head), *rest])
    return PathLookup(False)


def get_path(value: Any, path: str) -> PathLookup:
    """Resolve ``path`` in ``value``. A key present with a ``null`` value counts as found."""
    return _lookup(value, parse_path(path))


def is_present(value: Any, path: str) -> bool:
    """Found and not empty (``None``, ``""``, ``[]`` and ``{}`` count as missing)."""
    lookup = get_path(value, path)
    if not lookup.found:
        return False
    return lookup.value not in (None, "", [], {})
