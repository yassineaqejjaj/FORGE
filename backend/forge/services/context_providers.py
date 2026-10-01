"""Context preparation before an agent call (docs/ARCHITECTURE.md §8 step 3).

``agent.context_config``::

    {"source": "scenario" | "orbit_snapshot" | "orbit_live" | "none",
     "orbit": {"project": "<slug>", "snapshot": "<name>", "version": "latest" | "<n>",
               "credential_id": "<uuid>", "base_url": "https://orbit…", "optional": false,
               "merge": true, "timeout_seconds": 20, "params": {...}}}

* ``scenario`` (default) — the scenario's own context;
* ``orbit_snapshot`` — ``GET {base}/api/v1/projects/{project}/snapshots/{name}/{version}``: pinned,
  reproducible context; the resolved version and content hash are recorded;
* ``orbit_live`` — ``POST {base}/api/v1/projects/{project}/context`` with ``{"task": …}``: live
  assembly; the ORBIT request id is recorded;
* ``none`` — no context at all.

ORBIT documents are merged after the scenario documents unless ``merge`` is false. A failure fails
the run with a French message unless ``orbit.optional`` is true (then the scenario context is used
and a warning is traced).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

from sqlalchemy.ext.asyncio import AsyncSession

from forge.adapters.http import create_client, request_json
from forge.config import settings
from forge.domain.enums import ContextSource
from forge.domain.hashing import content_hash
from forge.domain.types import AgentExecutionError, AgentSpec, ScenarioSpec
from forge.infra.security import SecretDecryptionError
from forge.services.credentials import resolve_credentials

logger = logging.getLogger("forge.context")

ORBIT_TARGET = "ORBIT"
DEFAULT_TIMEOUT_SECONDS = 20.0


@dataclass(slots=True)
class PreparedContext:
    """Context handed to the agent + provenance recorded in the ``context_prepared`` event."""

    context: dict[str, Any]
    source: ContextSource
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def documents_count(self) -> int:
        return len([d for d in self.context.get("documents") or [] if isinstance(d, dict)])


class ContextPreparationError(Exception):
    """Context could not be prepared (message is user-facing, French)."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


@dataclass(slots=True)
class OrbitConfig:
    project: str
    base_url: str
    api_key: str | None
    snapshot: str | None
    version: str
    optional: bool
    merge: bool
    timeout_seconds: float
    params: dict[str, Any]


async def prepare_context(
    session: AsyncSession,
    scenario: ScenarioSpec,
    agent: AgentSpec,
    *,
    run_id: str | None = None,
    base_context: dict[str, Any] | None = None,
) -> PreparedContext:
    """Build the context of one call. ``base_context`` replaces the scenario context (ad-hoc tests)."""
    source = _source(agent.context_config)
    base = dict(base_context if base_context is not None else scenario.context or {})
    if source == ContextSource.none:
        return PreparedContext(context={}, source=source)
    if source == ContextSource.scenario:
        return PreparedContext(context=base, source=source)
    orbit = await _orbit_config(session, agent.context_config)
    try:
        if source == ContextSource.orbit_snapshot:
            return await _from_snapshot(orbit, base, run_id=run_id)
        return await _from_live(orbit, base, scenario, run_id=run_id)
    except ContextPreparationError as exc:
        if not orbit.optional:
            raise
        logger.warning(
            "Optional ORBIT context unavailable (%s): falling back to the scenario context", source
        )
        return PreparedContext(
            context=base,
            source=ContextSource.scenario,
            metadata={
                "requested_source": source.value,
                "orbit_error": str(exc),
                "orbit_project": orbit.project,
            },
            warnings=[f"{exc} — contexte du scénario utilisé (ORBIT optionnel)"],
        )


def _source(config: dict[str, Any]) -> ContextSource:
    raw = str(config.get("source") or ContextSource.scenario.value)
    try:
        return ContextSource(raw)
    except ValueError as exc:
        raise ContextPreparationError(f"Source de contexte inconnue : « {raw} »") from exc


async def _orbit_config(session: AsyncSession, config: dict[str, Any]) -> OrbitConfig:
    orbit = dict(config.get("orbit") or {})
    optional = bool(orbit.get("optional", False))
    project = str(orbit.get("project") or "").strip()
    try:
        credentials = await resolve_credentials(session, orbit.get("credential_id"))
    except (SecretDecryptionError, ValueError) as exc:
        raise ContextPreparationError(f"Identifiant ORBIT illisible : {exc}") from exc
    base_url = str(orbit.get("base_url") or credentials.get("base_url") or settings.orbit_base_url or "")
    if not project:
        raise ContextPreparationError("Contexte ORBIT : projet non configuré (context_config.orbit.project)")
    if not base_url:
        raise ContextPreparationError(
            "Contexte ORBIT : URL non configurée (context_config.orbit.base_url ou FORGE_ORBIT_BASE_URL)"
        )
    return OrbitConfig(
        project=project,
        base_url=base_url.rstrip("/"),
        api_key=credentials.get("api_key"),
        snapshot=str(orbit["snapshot"]).strip() if orbit.get("snapshot") else None,
        version=str(orbit.get("version") or "latest"),
        optional=optional,
        merge=bool(orbit.get("merge", True)),
        timeout_seconds=float(orbit.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        params=dict(orbit.get("params") or {}),
    )


def _headers(orbit: OrbitConfig, run_id: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if orbit.api_key:
        headers["Authorization"] = f"Bearer {orbit.api_key}"
    if run_id:
        headers["X-Forge-Run-Id"] = run_id
    return headers


async def _call_orbit(
    orbit: OrbitConfig, method: str, path: str, *, run_id: str | None, payload: Any = None
) -> tuple[Any, dict[str, str]]:
    url = f"{orbit.base_url}{path}"
    try:
        async with create_client(timeout=orbit.timeout_seconds, headers=_headers(orbit, run_id)) as client:
            data, response = await request_json(
                client, method, url, target=ORBIT_TARGET, json_payload=payload
            )
    except AgentExecutionError as exc:
        raise ContextPreparationError(
            f"Préparation du contexte ORBIT impossible : {exc}", retryable=exc.retryable
        ) from exc
    if not isinstance(data, dict):
        raise ContextPreparationError("Préparation du contexte ORBIT impossible : réponse JSON inattendue")
    return data, dict(response.headers)


async def _from_snapshot(orbit: OrbitConfig, base: dict[str, Any], *, run_id: str | None) -> PreparedContext:
    if not orbit.snapshot:
        raise ContextPreparationError(
            "Contexte ORBIT : snapshot non configuré (context_config.orbit.snapshot)"
        )
    path = (
        f"/api/v1/projects/{quote(orbit.project, safe='')}/snapshots/"
        f"{quote(orbit.snapshot, safe='')}/{quote(orbit.version, safe='')}"
    )
    data, _ = await _call_orbit(orbit, "GET", path, run_id=run_id)
    snapshot = data.get("snapshot") if isinstance(data.get("snapshot"), dict) else data
    documents = orbit_documents(snapshot)
    resolved_version = snapshot.get("version") or snapshot.get("snapshot_version") or orbit.version
    digest = snapshot.get("content_hash") or snapshot.get("hash") or content_hash(documents)
    context = _merge(base, documents, snapshot, merge=orbit.merge)
    return PreparedContext(
        context=context,
        source=ContextSource.orbit_snapshot,
        metadata={
            "orbit_project": orbit.project,
            "snapshot": orbit.snapshot,
            "snapshot_requested_version": orbit.version,
            "snapshot_version": str(resolved_version),
            "snapshot_hash": str(digest),
            "orbit_documents": len(documents),
        },
    )


async def _from_live(
    orbit: OrbitConfig, base: dict[str, Any], scenario: ScenarioSpec, *, run_id: str | None
) -> PreparedContext:
    task = str(orbit.params.pop("task", None) or scenario.input.get("prompt") or "")
    payload = {"task": task, **orbit.params}
    path = f"/api/v1/projects/{quote(orbit.project, safe='')}/context"
    data, headers = await _call_orbit(orbit, "POST", path, run_id=run_id, payload=payload)
    documents = orbit_documents(data)
    request_id = data.get("request_id") or data.get("id") or _header(headers, "x-request-id")
    context = _merge(base, documents, data, merge=orbit.merge)
    return PreparedContext(
        context=context,
        source=ContextSource.orbit_live,
        metadata={
            "orbit_project": orbit.project,
            "orbit_request_id": str(request_id) if request_id else None,
            "orbit_documents": len(documents),
            "orbit_context_hash": content_hash(documents),
        },
    )


def _header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def orbit_documents(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalise ORBIT items (``documents`` / ``items`` / ``context.documents``) to FORGE documents."""
    raw = data.get("documents") or data.get("items")
    if raw is None and isinstance(data.get("context"), dict):
        raw = data["context"].get("documents")
    documents: list[dict[str, Any]] = []
    for index, item in enumerate(raw or []):
        if isinstance(item, str):
            item = {"content": item}
        if not isinstance(item, dict):
            continue
        doc_id = item.get("id") or item.get("document_id") or item.get("key") or f"orbit-{index + 1}"
        documents.append(
            {
                "id": str(doc_id),
                "title": str(item.get("title") or item.get("name") or doc_id),
                "content": str(item.get("content") or item.get("text") or item.get("body") or ""),
                "source": str(item.get("source") or "orbit"),
                **({"classification": item["classification"]} if "classification" in item else {}),
            }
        )
    return documents


def _merge(
    base: dict[str, Any], documents: list[dict[str, Any]], data: dict[str, Any], *, merge: bool
) -> dict[str, Any]:
    context: dict[str, Any] = dict(base) if merge else {}
    existing = [d for d in context.get("documents") or [] if isinstance(d, dict)]
    known = {str(d.get("id")) for d in existing}
    context["documents"] = existing + [d for d in documents if d["id"] not in known]
    facts = data.get("facts") or data.get("memory")
    if isinstance(facts, list) and facts:
        context["facts"] = list(context.get("facts") or []) + [str(f) for f in facts]
    text = data.get("context") if isinstance(data.get("context"), str) else data.get("text")
    if isinstance(text, str) and text.strip():
        context["orbit_context"] = text
    return context
