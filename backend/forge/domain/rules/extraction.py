"""JSON extraction from agent outputs and judge answers (Markdown fences, surrounding prose).

Order of attempts: the whole text, then fenced blocks (```json …```, then any ``` fence), then the
first balanced ``{…}`` / ``[…]`` of the text. Trailing commas are tolerated as a last resort.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_FENCE = re.compile(r"```[ \t]*(?P<lang>[\w+-]*)[^\n]*\n(?P<body>.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


@dataclass(frozen=True, slots=True)
class ExtractedJson:
    ok: bool
    value: Any = None
    #: ``native`` (``output_json``), ``text``, ``fence``, ``embedded`` or ``none``
    source: str = "none"
    error: str | None = None


def _loads(text: str) -> tuple[bool, Any, str | None]:
    try:
        return True, json.loads(text), None
    except (ValueError, RecursionError) as exc:
        repaired = _TRAILING_COMMA.sub(r"\1", text)
        if repaired != text:
            try:
                return True, json.loads(repaired), None
            except (ValueError, RecursionError):
                pass
        return False, None, str(exc)


def fenced_blocks(text: str) -> list[tuple[str, str]]:
    """``(language, body)`` of every Markdown code fence, JSON-tagged blocks first."""
    blocks = [(m.group("lang").lower(), m.group("body")) for m in _FENCE.finditer(text or "")]
    return sorted(blocks, key=lambda b: 0 if b[0] in ("json", "jsonc", "json5") else 1)


def _balanced_candidates(text: str) -> list[str]:
    """Substrings starting at each ``{``/``[`` and ending at the matching bracket (string-aware)."""
    candidates: list[str] = []
    starts = [i for i, ch in enumerate(text) if ch in "{["]
    for start in starts[:50]:
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
        if candidates and opener == "{":
            break
    return candidates


def extract_json(text: str | None, *, native: Any = None) -> ExtractedJson:
    """Best-effort JSON value of an output (``native`` = structured output reported by the agent)."""
    if native is not None:
        return ExtractedJson(True, native, "native")
    raw = (text or "").strip()
    if not raw:
        return ExtractedJson(False, error="Sortie vide")
    ok, value, error = _loads(raw)
    if ok:
        return ExtractedJson(True, value, "text")
    first_error = error
    for _lang, body in fenced_blocks(raw):
        ok, value, _ = _loads(body.strip())
        if ok:
            return ExtractedJson(True, value, "fence")
    for candidate in _balanced_candidates(raw):
        ok, value, _ = _loads(candidate)
        if ok and isinstance(value, dict | list):
            return ExtractedJson(True, value, "embedded")
    return ExtractedJson(False, error=first_error or "JSON introuvable")


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """First JSON *object* found in ``text`` (judge answers), ``None`` otherwise."""
    result = extract_json(text)
    if result.ok and isinstance(result.value, dict):
        return result.value
    # A bare list of criteria is accepted as ``{"criteria": [...]}``.
    if result.ok and isinstance(result.value, list) and all(isinstance(i, dict) for i in result.value):
        return {"criteria": result.value}
    raw = text or ""
    for candidate in _balanced_candidates(raw):
        ok, value, _ = _loads(candidate)
        if ok and isinstance(value, dict):
            return value
    return None
