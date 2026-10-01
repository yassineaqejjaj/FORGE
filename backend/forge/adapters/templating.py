"""Request templates and response paths of the ``custom_api`` mapped mode (docs/AGENT_PROTOCOL.md §5).

* placeholders ``{{input.prompt}}``, ``{{context}}``, ``{{system_prompt}}``, ``{{credentials.api_key}}``…
  are resolved against a variables dict; a string made of a single placeholder is replaced by the raw
  value (objects stay objects), otherwise values are interpolated (JSON for non-strings);
* simple JSON paths ``a.b[0].c`` (optional ``$.`` prefix) read values from responses.
"""

from __future__ import annotations

import json
import re
from typing import Any

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.\[\]-]+)\s*\}\}")
_PATH_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")

_MISSING = object()


def json_path_get(data: Any, path: str | None, default: Any = None) -> Any:
    """Value at ``path`` (``choices[0].message.content``) or ``default`` when absent."""
    if path is None or path == "":
        return default
    text = path.strip()
    if text in ("$", "."):
        return data
    text = text.removeprefix("$.").removeprefix("$")
    current = data
    for match in _PATH_TOKEN.finditer(text):
        key, index = match.group(1), match.group(2)
        if index is not None:
            if not isinstance(current, list) or int(index) >= len(current):
                return default
            current = current[int(index)]
        elif isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return default
    return current


def lookup(variables: dict[str, Any], path: str) -> Any:
    value = json_path_get(variables, path, _MISSING)
    return None if value is _MISSING else value


def render(template: Any, variables: dict[str, Any]) -> Any:
    """Recursively render placeholders in strings of ``template`` (dicts, lists, scalars)."""
    if isinstance(template, str):
        return render_string(template, variables)
    if isinstance(template, dict):
        return {render_string(str(k), variables): render(v, variables) for k, v in template.items()}
    if isinstance(template, list):
        return [render(item, variables) for item in template]
    return template


def render_string(template: str, variables: dict[str, Any]) -> Any:
    whole = PLACEHOLDER.fullmatch(template.strip())
    if whole:
        return lookup(variables, whole.group(1))
    return PLACEHOLDER.sub(lambda m: _as_text(lookup(variables, m.group(1))), template)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)
