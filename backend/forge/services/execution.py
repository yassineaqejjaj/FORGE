"""Agent Runner (owner: execution) — see docs/ARCHITECTURE.md §8. STUB: replaced by the module owner."""

from __future__ import annotations

from typing import Any


async def execute_run_job(session: Any, job: Any) -> None:
    raise NotImplementedError("Agent Runner non implémenté")


async def invoke_adhoc(
    session: Any, agent_version: Any, *, input: dict[str, Any], context: dict[str, Any] | None = None
) -> Any:
    """Invoke an agent version outside any run (``POST /agent-versions/{id}/test``)."""
    raise NotImplementedError("Agent Runner non implémenté")
