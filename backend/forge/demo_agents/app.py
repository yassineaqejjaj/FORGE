"""Demo agents service (``uvicorn forge.demo_agents.app:app``, port 8190) — FORGE Agent Protocol v1.

* ``GET /health`` — liveness;
* ``GET /agents`` — catalog (agents, versions, simulated traits, endpoints);
* ``POST /agents/{slug}/{version}/invoke`` — FAP request → FAP response (output, events, usage, cost).

Agents are **simulated and deterministic** (same scenario version × repetition ⇒ same answer): no
LLM is called. Latency is simulated with ``asyncio.sleep`` (scaled by ``FORGE_DEMO_LATENCY_SCALE``
or ``parameters.latency_scale``; 0 disables waiting). See docs/DEMO_AGENTS.md.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from forge.demo_agents import otlp
from forge.demo_agents.catalog import AGENTS, find
from forge.demo_agents.common import PROTOCOL, AgentOutput, DemoRequest, parse_request

MAX_LATENCY_SCALE = 10.0

app = FastAPI(
    title="FORGE — agents de démonstration",
    version="1.0.0",
    description="Agents simulés et déterministes parlant le FORGE Agent Protocol v1.",
)


def _error(
    status: int, message: str, *, error_type: str = "EXECUTION_ERROR", retryable: bool = False
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "protocol": PROTOCOL,
            "error": {"type": error_type, "message": message, "retryable": retryable},
        },
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "agents": len(AGENTS), "protocol": PROTOCOL}


@app.get("/agents")
async def catalog() -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "agents": [
            {
                "slug": agent.slug,
                "name": agent.name,
                "description": agent.description,
                "tasks": list(agent.tasks),
                "versions": [
                    {
                        "version": v.version,
                        "model": v.model,
                        "summary": v.summary,
                        "traits": list(v.traits),
                        "endpoint": f"/agents/{agent.slug}/{v.version}/invoke",
                    }
                    for v in agent.versions
                ],
            }
            for agent in AGENTS.values()
        ],
    }


@app.post("/agents/{slug}/{version}/invoke")
async def invoke(slug: str, version: str, request: Request) -> JSONResponse:
    found = find(slug, version)
    if found is None:
        return _error(404, f"Agent de démonstration inconnu : {slug} v{version}")
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "Corps JSON invalide")
    if not isinstance(body, dict):
        return _error(400, "Objet JSON attendu (FORGE Agent Protocol v1)")
    demo = parse_request(body, dict(request.headers))
    failure = _simulated_failure(demo)
    if failure is not None:
        return failure
    agent, info = found
    started_at = otlp.now()
    output = agent.run(demo, info.version)
    await asyncio.sleep(output.log.cursor_ms / 1000 * _latency_scale(demo))
    events = output.log.events
    delivery = "inline"
    warnings: list[str] = []
    if demo.parameters.get("white_box"):
        export = otlp.build_export(
            demo, agent_name=agent.name, model=output.model, events=events, started_at=started_at
        )
        problem = await otlp.push(export) if export else "traceparent absent"
        if problem is None:
            delivery, events = "otlp", []
        else:
            warnings.append(f"Mode boîte blanche : {problem} — événements renvoyés dans la réponse")
    return JSONResponse(_response(demo, agent.slug, info.version, output, events, delivery, warnings))


def _response(
    demo: DemoRequest,
    slug: str,
    version: str,
    output: AgentOutput,
    events: list[dict[str, Any]],
    delivery: str,
    warnings: list[str],
) -> dict[str, Any]:
    log = output.log
    return {
        "protocol": PROTOCOL,
        "output": output.text,
        "output_json": output.output_json,
        "messages": [{"role": "assistant", "content": output.text}],
        "events": events,
        "usage": {
            "input_tokens": log.input_tokens,
            "output_tokens": log.output_tokens,
            "model_calls": log.model_calls,
            "tool_calls": sum(1 for e in log.events if e["type"] == "tool_call"),
        },
        "cost": round(log.cost, 6),
        "model": output.model,
        "metadata": {
            "agent": slug,
            "version": version,
            "simulated": True,
            "simulated_latency_ms": round(log.cursor_ms, 1),
            "simulated_behaviors": output.behaviors,
            "trace_delivery": delivery,
            "repetition": demo.repetition,
            "warnings": warnings,
        },
    }


def _latency_scale(demo: DemoRequest) -> float:
    raw = demo.parameters.get("latency_scale", os.environ.get("FORGE_DEMO_LATENCY_SCALE", "1"))
    try:
        return min(MAX_LATENCY_SCALE, max(0.0, float(raw)))
    except (TypeError, ValueError):
        return 1.0


def _simulated_failure(demo: DemoRequest) -> JSONResponse | None:
    """``parameters.simulate_failure``: ``transient`` (HTTP 503 on the first attempt) or ``permanent``."""
    mode = str(demo.parameters.get("simulate_failure") or "")
    if mode == "transient" and demo.attempt <= 1:
        return _error(503, "Service momentanément indisponible (panne simulée)", retryable=True)
    if mode == "permanent":
        return _error(422, "Requête refusée par l'agent (erreur simulée)")
    return None
