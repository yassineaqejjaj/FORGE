"""NOVA agents via the NOVA Agent Protocol — docs §8.1 and docs/AGENT_PROTOCOL.md §6.

Request: FAP body + ``nova_agent_id``, ``POST {base}{path}`` with ``adapter_config.path`` (default
``/v1/agents/{nova_agent_id}/runs``). Response: FAP response + multi-agent details:

* ``handoffs``: ``[{"from", "to", "reason"?, "offset_ms"?, "duration_ms"?, "input"?, "output"?}]``
* ``agents``: ``[{"name", "role"?, "events": [FAP events], "usage"?}]``

Each handoff (and each sub-agent without an explicit handoff) becomes an ``agent_handoff`` event;
sub-agent events are nested under their handoff and tagged with ``attributes.agent``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from forge.adapters.base import (
    build_protocol_body,
    credential_headers,
    http_timeout,
    propagation_headers,
    result_from_protocol,
)
from forge.adapters.http import create_client, request_json
from forge.domain.enums import AdapterKind, TraceEventSource, TraceEventType
from forge.domain.traces.protocol import parse_protocol_events
from forge.domain.types import AgentExecutionError, AgentRequest, AgentResult, TraceEventData

DEFAULT_PATH = "/v1/agents/{nova_agent_id}/runs"
TARGET = "NOVA"


class NovaAdapter:
    kind = AdapterKind.nova

    async def invoke(self, request: AgentRequest, recorder: Any) -> AgentResult:
        config = request.agent.adapter_config
        nova_agent_id = str(config.get("nova_agent_id") or "").strip()
        if not nova_agent_id:
            raise AgentExecutionError("Identifiant d'agent NOVA manquant (adapter_config.nova_agent_id)")
        body = build_protocol_body(request)
        body["nova_agent_id"] = nova_agent_id
        if config.get("nova_options"):
            body["options"] = dict(config["nova_options"])
        headers = {**credential_headers(request.agent.credentials), **propagation_headers(request)}
        if request.agent.credentials.get("api_key"):
            headers["Authorization"] = f"Bearer {request.agent.credentials['api_key']}"
        started_at = datetime.now(UTC)
        async with create_client(timeout=http_timeout(request)) as client:
            data, _ = await request_json(
                client,
                "POST",
                nova_url(request, nova_agent_id),
                target=TARGET,
                json_payload=body,
                headers=headers,
            )
        extra = multi_agent_events(data, started_at=started_at) if isinstance(data, dict) else []
        result = result_from_protocol(data, recorder=recorder, started_at=started_at, key_prefix="nova:",
                                      extra_events=extra)  # fmt: skip
        result.metadata.setdefault("nova_agent_id", nova_agent_id)
        result.metadata["handoffs"] = sum(1 for e in extra if e.type == TraceEventType.agent_handoff)
        return result


def nova_url(request: AgentRequest, nova_agent_id: str) -> str:
    agent = request.agent
    base = str(
        agent.credentials.get("base_url") or agent.adapter_config.get("base_url") or agent.endpoint or ""
    ).rstrip("/")
    if not base:
        raise AgentExecutionError("URL de NOVA manquante (identifiant NOVA, base_url ou endpoint)")
    path = str(agent.adapter_config.get("path") or DEFAULT_PATH).replace("{nova_agent_id}", nova_agent_id)
    return f"{base}/{path.lstrip('/')}"


def multi_agent_events(data: dict[str, Any], *, started_at: datetime) -> list[TraceEventData]:
    """``handoffs`` / ``agents`` of a NOVA response → ``agent_handoff`` events + nested sub-agent events."""
    events: list[TraceEventData] = []
    handoff_keys: dict[str, str] = {}
    handoffs = [h for h in data.get("handoffs") or [] if isinstance(h, dict)]
    for index, handoff in enumerate(handoffs):
        target = str(handoff.get("to") or handoff.get("agent") or f"agent-{index + 1}")
        item = {
            "type": TraceEventType.agent_handoff.value,
            "id": f"handoff-{index + 1}",
            "name": f"Délégation à {target}",
            "offset_ms": handoff.get("offset_ms"),
            "started_at": handoff.get("started_at"),
            "duration_ms": handoff.get("duration_ms"),
            "input": handoff.get("input"),
            "output": handoff.get("output"),
            "attributes": {"agent": target, "from": handoff.get("from"), "to": target,
                           "reason": handoff.get("reason")},
        }  # fmt: skip
        (event,) = parse_protocol_events([item], base_time=started_at, key_prefix="nova-handoff:")
        events.append(event)
        handoff_keys.setdefault(target, event.key)
    for agent in (a for a in data.get("agents") or [] if isinstance(a, dict)):
        events += _sub_agent_events(agent, started_at=started_at, handoff_keys=handoff_keys)
    return events


def _sub_agent_events(
    agent: dict[str, Any],
    *,
    started_at: datetime,
    handoff_keys: dict[str, str],
) -> list[TraceEventData]:
    name = str(agent.get("name") or agent.get("id") or "sous-agent")
    created: list[TraceEventData] = []
    parent_key = handoff_keys.get(name)
    sub_events = parse_protocol_events(
        agent.get("events") if isinstance(agent.get("events"), list) else [],
        base_time=started_at,
        source=TraceEventSource.adapter,
        key_prefix=f"nova-agent:{name}:",
        extra_attributes={"agent": name},
    )
    if parent_key is None:
        first = sub_events[0].started_at if sub_events else started_at
        last = max((e.ended_at or e.started_at for e in sub_events), default=first)
        handoff = TraceEventData(
            type=TraceEventType.agent_handoff,
            name=f"Délégation à {name}",
            started_at=first,
            ended_at=last,
            key=f"nova-agent:{name}",
            attributes={"agent": name, "to": name, "role": agent.get("role")},
            source=TraceEventSource.adapter,
        )
        created.append(handoff)
        parent_key = handoff.key
    for event in sub_events:
        if event.parent_key is None:
            event.parent_key = parent_key
    return created + sub_events
