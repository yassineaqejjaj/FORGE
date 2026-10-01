"""Any HTTP agent — docs §8.1 and docs/AGENT_PROTOCOL.md.

``adapter_config.mode``:

* ``forge`` (default) — FORGE Agent Protocol v1: ``POST <endpoint>`` with the FAP body, FAP response
  (output, events, usage, cost);
* ``mapped`` — arbitrary API: ``method``, ``url`` (or the version endpoint), ``headers`` (values may
  use ``{{credentials.api_key}}``), ``body_template`` with ``{{input.prompt}}``, ``{{context}}``,
  ``{{system_prompt}}``… placeholders, and response paths ``output_path``, ``output_json_path``,
  ``usage_paths`` (``input_tokens`` / ``output_tokens``), ``cost_path``, ``events_path``.

Tracing headers (``traceparent``, ``X-Forge-Run-Id``, ``X-Forge-Scenario-Version``) are always sent.
"""

from __future__ import annotations

import json
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
from forge.adapters.templating import json_path_get, render
from forge.domain.enums import AdapterKind, TraceEventType
from forge.domain.types import AgentExecutionError, AgentRequest, AgentResult, to_dict

TARGET = "L'agent"
DEFAULT_OUTPUT_PATH = "output"


class CustomApiAdapter:
    kind = AdapterKind.custom_api

    async def invoke(self, request: AgentRequest, recorder: Any) -> AgentResult:
        mode = str(request.agent.adapter_config.get("mode") or "forge").lower()
        if mode == "mapped":
            return await self._invoke_mapped(request, recorder)
        if mode != "forge":
            raise AgentExecutionError(f"Mode d'adapter custom_api inconnu : « {mode} » (forge ou mapped)")
        return await self._invoke_protocol(request, recorder)

    # --- FORGE Agent Protocol ----------------------------------------------------------------------

    async def _invoke_protocol(self, request: AgentRequest, recorder: Any) -> AgentResult:
        url = resolve_url(request)
        headers = {**self._auth_headers(request), **propagation_headers(request)}
        headers.update(_rendered_headers(request))
        started_at = datetime.now(UTC)
        async with create_client(timeout=http_timeout(request)) as client:
            data, response = await request_json(
                client, "POST", url, target=TARGET, json_payload=build_protocol_body(request), headers=headers
            )
        result = result_from_protocol(data, recorder=recorder, started_at=started_at)
        result.metadata.setdefault("http_status", response.status_code)
        return result

    def _auth_headers(self, request: AgentRequest) -> dict[str, str]:
        credentials = request.agent.credentials
        headers = credential_headers(credentials)
        if credentials.get("api_key") and not any(k.lower() == "authorization" for k in headers):
            headers["Authorization"] = f"Bearer {credentials['api_key']}"
        return headers

    # --- Mapped mode --------------------------------------------------------------------------------

    async def _invoke_mapped(self, request: AgentRequest, recorder: Any) -> AgentResult:
        config = request.agent.adapter_config
        variables = template_variables(request)
        method = str(config.get("method") or "POST").upper()
        url = str(render(str(config.get("url") or resolve_url(request)), variables))
        headers = {**credential_headers(request.agent.credentials), **propagation_headers(request)}
        headers.update(_rendered_headers(request, variables))
        body = render(
            config.get("body_template", {"input": "{{input}}", "context": "{{context}}"}), variables
        )
        started_at = datetime.now(UTC)
        with recorder.span(
            TraceEventType.custom, f"Appel HTTP {method}", attributes={"method": method, "mapped": True}
        ) as handle:
            async with create_client(timeout=http_timeout(request)) as client:
                data, response = await request_json(
                    client,
                    method,
                    url,
                    target=TARGET,
                    json_payload=body if method not in ("GET", "DELETE") else None,
                    params=body if method in ("GET", "DELETE") and isinstance(body, dict) else None,
                    headers=headers,
                )
            handle.set_attributes(http_status=response.status_code)
        return result_from_protocol(
            mapped_response(data, config), recorder=recorder, started_at=started_at, key_prefix="mapped:"
        )


def resolve_url(request: AgentRequest) -> str:
    """Absolute endpoint: version endpoint, ``adapter_config.url``, relative paths joined to ``base_url``."""
    agent = request.agent
    endpoint = str(agent.adapter_config.get("url") or agent.endpoint or "").strip()
    base = str(agent.credentials.get("base_url") or agent.adapter_config.get("base_url") or "").rstrip("/")
    if not endpoint and not base:
        raise AgentExecutionError("Aucun endpoint configuré pour cet agent (champ endpoint de la version)")
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    if not base:
        raise AgentExecutionError(
            f"Endpoint relatif « {endpoint} » sans URL de base (identifiant ou base_url)"
        )
    return f"{base}/{endpoint.lstrip('/')}" if endpoint else base


def template_variables(request: AgentRequest) -> dict[str, Any]:
    view = request.scenario.agent_view()
    return {
        "input": view["input"],
        "prompt": view["input"].get("prompt", ""),
        "context": request.context,
        "context_text": json.dumps(request.context, ensure_ascii=False),
        "constraints": view["constraints"],
        "system_prompt": request.agent.system_prompt,
        "run_id": request.run_id,
        "trace_id": request.otel_trace_id,
        "scenario_version_id": view["scenario_version_id"],
        "agent": {"name": request.agent.agent_name, "version": request.agent.version},
        "model": to_dict(request.agent.model) if request.agent.model else None,
        "parameters": dict(request.agent.adapter_config.get("parameters") or {}),
        "credentials": dict(request.agent.credentials),
    }


def _rendered_headers(request: AgentRequest, variables: dict[str, Any] | None = None) -> dict[str, str]:
    configured = request.agent.adapter_config.get("headers") or {}
    if not isinstance(configured, dict) or not configured:
        return {}
    rendered = render(configured, variables or template_variables(request))
    return {str(k): str(v) for k, v in rendered.items() if v not in (None, "")}


def mapped_response(data: Any, config: dict[str, Any]) -> dict[str, Any]:
    """Translate an arbitrary JSON response into a FAP response using the configured paths."""
    output = json_path_get(data, str(config.get("output_path") or DEFAULT_OUTPUT_PATH))
    if output is None:
        raise AgentExecutionError(
            f"Réponse de l'agent sans valeur au chemin « {config.get('output_path') or DEFAULT_OUTPUT_PATH} »"
        )
    mapped: dict[str, Any] = {"output": output if isinstance(output, str | dict | list) else str(output)}
    if config.get("output_json_path"):
        mapped["output_json"] = json_path_get(data, str(config["output_json_path"]))
    usage_paths = config.get("usage_paths") or {}
    if isinstance(usage_paths, dict):
        mapped["usage"] = {name: json_path_get(data, str(path)) for name, path in usage_paths.items() if path}
    if config.get("cost_path"):
        mapped["cost"] = json_path_get(data, str(config["cost_path"]))
    if config.get("events_path"):
        events = json_path_get(data, str(config["events_path"]))
        mapped["events"] = events if isinstance(events, list) else []
    if config.get("error_path"):
        error = json_path_get(data, str(config["error_path"]))
        if error:
            mapped["error"] = error
    return mapped
