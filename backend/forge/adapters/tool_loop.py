"""FORGE-driven tool loop shared by the OpenAI and Anthropic adapters (docs §8.1).

FORGE declares the agent's tools to the model and answers each tool call with the scenario's
``ToolMock`` entries: the first mock whose ``tool`` matches and whose ``match`` is a subset of the
call arguments (case-insensitive string comparison) wins; no match → an error message is returned to
the model (the agent must cope with an unavailable tool). Every call is traced as ``tool_call`` +
``tool_result``.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from forge.domain.enums import BuiltinErrorType, EventStatus, TraceEventType
from forge.domain.types import AgentRequest, ToolMock, ToolSpec

_INVALID_NAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")
MAX_TOOL_NAME = 64


@dataclass(slots=True)
class ToolOutcome:
    content: str  # what is sent back to the model
    is_error: bool
    mock_index: int | None


class ToolNames:
    """Provider-safe tool names (``jira.search`` → ``jira_search``) and the reverse mapping."""

    def __init__(self, tools: list[ToolSpec]) -> None:
        self._to_wire: dict[str, str] = {}
        self._from_wire: dict[str, str] = {}
        for tool in tools:
            wire = _INVALID_NAME_CHARS.sub("_", tool.name)[:MAX_TOOL_NAME] or "tool"
            base, suffix = wire, 2
            while wire in self._from_wire:
                wire = f"{base[: MAX_TOOL_NAME - 3]}_{suffix}"
                suffix += 1
            self._to_wire[tool.name] = wire
            self._from_wire[wire] = tool.name

    def wire(self, name: str) -> str:
        return self._to_wire.get(name, name)

    def original(self, wire_name: str) -> str:
        return self._from_wire.get(wire_name, wire_name)


def _normalise(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().casefold()
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).casefold()


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _matches(v, actual[k]) for k, v in expected.items()
        )
    return _normalise(expected) == _normalise(actual)


def find_mock(mocks: list[ToolMock], tool: str, arguments: Any) -> tuple[int, ToolMock] | None:
    """First mock for ``tool`` whose ``match`` is a subset of ``arguments``."""
    args = arguments if isinstance(arguments, dict) else {}
    for index, mock in enumerate(mocks):
        if mock.tool != tool:
            continue
        if mock.match is None or _matches(mock.match, args):
            return index, mock
    return None


def parse_arguments(raw: Any) -> Any:
    """Tool-call arguments as sent by the model (JSON string or object)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {"_raw": raw}
    return {} if raw is None else {"_raw": raw}


def _content(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


async def run_tool(
    request: AgentRequest, recorder: Any, *, tool: str, arguments: Any, call_id: str, step: int
) -> ToolOutcome:
    """Answer one tool call from the scenario mocks and trace ``tool_call`` + ``tool_result``."""
    recorder.count_tool_call()
    call_key = recorder.event(
        TraceEventType.tool_call,
        tool,
        input=arguments,
        attributes={"tool": tool, "arguments": arguments, "call_id": call_id, "step": step},
    )
    found = find_mock(request.scenario.tool_mocks, tool, arguments)
    if found is None:
        message = f"Outil « {tool} » indisponible : aucune réponse simulée ne correspond à cet appel."
        recorder.event(
            TraceEventType.tool_result,
            tool,
            output=message,
            status=EventStatus.error,
            parent=call_key,
            attributes={"tool": tool, "call_id": call_id, "error": message,
                        "error_type": BuiltinErrorType.TOOL_FAILURE, "mocked": False},
        )  # fmt: skip
        return ToolOutcome(content=message, is_error=True, mock_index=None)
    index, mock = found
    if mock.latency_ms:
        await asyncio.sleep(mock.latency_ms / 1000)
    if mock.error:
        recorder.event(
            TraceEventType.tool_result,
            tool,
            output=mock.error,
            status=EventStatus.error,
            parent=call_key,
            duration_ms=mock.latency_ms or None,
            attributes={"tool": tool, "call_id": call_id, "error": mock.error,
                        "error_type": BuiltinErrorType.TOOL_FAILURE, "mock_index": index, "mocked": True},
        )  # fmt: skip
        return ToolOutcome(
            content=f"Erreur de l'outil « {tool} » : {mock.error}", is_error=True, mock_index=index
        )
    recorder.event(
        TraceEventType.tool_result,
        tool,
        output=mock.response,
        parent=call_key,
        duration_ms=mock.latency_ms or None,
        attributes={"tool": tool, "call_id": call_id, "mock_index": index, "mocked": True},
    )
    return ToolOutcome(content=_content(mock.response), is_error=False, mock_index=index)


def steps_exhausted(max_steps: int) -> str:
    return (
        f"Nombre maximal d'étapes atteint ({max_steps} appels au modèle) sans réponse finale "
        "— augmentez budget.max_steps ou vérifiez les outils simulés"
    )
