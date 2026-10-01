"""Agent Registry: agents, immutable agent versions, prompts, model and tool configurations (§6.1).

Versions are created from explicit fields or from ``base_version_id`` + overrides (improvement loop:
start from the evaluated version and change only what the feedback recommends). The behaviour of a
version is content-addressed (``versioning.agent_version_hash``): creating a version identical to
the agent's latest one is refused (409). Every created version is checked for benchmark
contamination (canaries / private expected outputs, ``forge.domain.scenarios.contamination``).
"""

from __future__ import annotations

import difflib
import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from forge.domain.enums import AdapterKind, ScenarioVisibility
from forge.domain.scenarios.contamination import (
    CanaryRef,
    PrivateOutputRef,
    ScenarioRef,
    agent_texts,
    check_contamination,
    flatten_text,
)
from forge.domain.serialization import from_dict
from forge.domain.types import AgentBudget, ToolSpec, to_dict
from forge.domain.versioning import agent_version_hash, model_configuration_hash, prompt_hash, tools_hash
from forge.infra.models import (
    Agent,
    AgentVersion,
    Judge,
    ModelConfiguration,
    PromptVersion,
    ProviderCredential,
    Scenario,
    ScenarioVersion,
    ToolConfiguration,
)
from forge.services import audit
from forge.services.audit import ActorLike
from forge.services.taxonomy import ConflictError, InvalidError, NotFoundError

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
PROMPT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,99}$")
TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
VERSION_LABEL_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._+-]{0,39}$")
_VARIABLE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

#: Adapters for which FORGE drives the model itself (a model configuration is required).
MODEL_DRIVEN_ADAPTERS = frozenset({AdapterKind.openai, AdapterKind.anthropic})
MODEL_FIELDS = (
    "provider",
    "model",
    "model_version",
    "temperature",
    "top_p",
    "max_tokens",
    "seed",
    "params",
    "input_cost_per_mtok",
    "output_cost_per_mtok",
)
AGENT_EDITABLE_FIELDS = ("name", "description", "provider", "tags", "metadata", "archived")


def slugify(text: str, *, sep: str = "-") -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", sep, ascii_text).strip(sep)


# =====================================================================================================
# Agents
# =====================================================================================================


@dataclass(slots=True)
class AgentListing:
    agent: Agent
    versions_count: int
    latest: AgentVersion | None
    latest_model: ModelConfiguration | None


async def get_agent(session: AsyncSession, agent_id: uuid.UUID) -> Agent:
    agent = await session.get(Agent, agent_id)
    if agent is None:
        raise NotFoundError("Agent introuvable")
    return agent


async def list_agents(
    session: AsyncSession,
    *,
    q: str | None = None,
    tag: str | None = None,
    provider: str | None = None,
    archived: bool | None = False,
    offset: int = 0,
    limit: int = 25,
) -> tuple[list[AgentListing], int]:
    conditions: list[Any] = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(Agent.name.ilike(pattern), Agent.slug.ilike(pattern), Agent.description.ilike(pattern))
        )
    if tag:
        conditions.append(Agent.tags.contains([tag]))
    if provider:
        conditions.append(Agent.provider == provider)
    if archived is not None:
        conditions.append(Agent.archived.is_(archived))
    total = await session.scalar(select(func.count()).select_from(Agent).where(*conditions))
    agents = list(
        await session.scalars(
            select(Agent).where(*conditions).order_by(Agent.name, Agent.slug).offset(offset).limit(limit)
        )
    )
    return await _listings(session, agents), int(total or 0)


async def _listings(session: AsyncSession, agents: Sequence[Agent]) -> list[AgentListing]:
    ids = [a.id for a in agents]
    if not ids:
        return []
    counts = dict(
        (
            await session.execute(
                select(AgentVersion.agent_id, func.count())
                .where(AgentVersion.agent_id.in_(ids))
                .group_by(AgentVersion.agent_id)
            )
        ).all()
    )
    latest_rows = await session.scalars(
        select(AgentVersion)
        .where(AgentVersion.agent_id.in_(ids))
        .distinct(AgentVersion.agent_id)
        .order_by(AgentVersion.agent_id, AgentVersion.version_number.desc())
    )
    latest = {v.agent_id: v for v in latest_rows}
    model_ids = {v.model_configuration_id for v in latest.values() if v.model_configuration_id}
    models: dict[uuid.UUID, ModelConfiguration] = {}
    if model_ids:
        models = {
            m.id: m
            for m in await session.scalars(
                select(ModelConfiguration).where(ModelConfiguration.id.in_(model_ids))
            )
        }
    listings = []
    for agent in agents:
        version = latest.get(agent.id)
        model = (
            models.get(version.model_configuration_id) if version and version.model_configuration_id else None
        )
        listings.append(AgentListing(agent, int(counts.get(agent.id, 0)), version, model))
    return listings


async def agent_listing(session: AsyncSession, agent: Agent) -> AgentListing:
    return (await _listings(session, [agent]))[0]


async def create_agent(
    session: AsyncSession,
    actor: ActorLike,
    *,
    name: str,
    slug: str | None = None,
    description: str = "",
    provider: str = "",
    tags: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
    owner_id: uuid.UUID | None = None,
) -> Agent:
    name = name.strip()
    if not name:
        raise InvalidError("Nom d'agent requis")
    slug = (slug or slugify(name)).strip()
    if not SLUG_RE.match(slug):
        raise InvalidError(
            "Identifiant (slug) invalide : minuscules, chiffres, « - » ou « _ », 2 à 80 caractères"
        )
    if await session.scalar(select(Agent.id).where(Agent.slug == slug)):
        raise ConflictError(f"Un agent existe déjà avec l'identifiant « {slug} »")
    agent = Agent(
        slug=slug,
        name=name,
        description=description.strip(),
        provider=provider.strip(),
        tags=_clean_tags(tags),
        metadata_=dict(metadata or {}),
        owner_id=owner_id,
    )
    session.add(agent)
    await session.flush()
    await audit.record(
        session,
        actor,
        "agent.create",
        "agent",
        agent.id,
        summary=f"Création de l'agent {agent.name} ({agent.slug})",
        details={"slug": slug, "provider": agent.provider},
    )
    return agent


def _clean_tags(tags: Sequence[str] | None) -> list[str]:
    seen: list[str] = []
    for tag in tags or []:
        tag = str(tag).strip()
        if tag and tag not in seen:
            seen.append(tag)
    return seen


async def update_agent(
    session: AsyncSession, actor: ActorLike, agent: Agent, changes: dict[str, Any]
) -> Agent:
    applied: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in AGENT_EDITABLE_FIELDS:
            continue
        if key == "name":
            value = str(value or "").strip()
            if not value:
                raise InvalidError("Nom d'agent requis")
        if key in ("description", "provider"):
            value = str(value or "").strip()
        if key == "tags":
            value = _clean_tags(value)
        if key == "metadata":
            value = dict(value or {})
        attr = "metadata_" if key == "metadata" else key
        if getattr(agent, attr) != value:
            applied[key] = value
            setattr(agent, attr, value)
    if applied:
        await session.flush()
        action = "agent.archive" if applied.get("archived") is True else "agent.update"
        await audit.record(
            session,
            actor,
            action,
            "agent",
            agent.id,
            summary=f"Modification de l'agent {agent.name}",
            details={"changes": applied},
        )
    return agent


# =====================================================================================================
# Prompts, model and tool configurations
# =====================================================================================================


def prompt_variables(content: str) -> list[str]:
    found: list[str] = []
    for name in _VARIABLE_RE.findall(content or ""):
        if name not in found:
            found.append(name)
    return found


async def latest_prompt(session: AsyncSession, name: str) -> PromptVersion | None:
    return await session.scalar(
        select(PromptVersion)
        .where(PromptVersion.name == name)
        .order_by(PromptVersion.version.desc())
        .limit(1)
    )


async def create_prompt_version(
    session: AsyncSession,
    actor: ActorLike,
    *,
    name: str,
    content: str,
    description: str = "",
    variables: Sequence[str] | None = None,
    created_by: uuid.UUID | None = None,
    reuse_identical: bool = False,
) -> PromptVersion:
    """Next version of prompt ``name``. Identical to the latest: 409, or reuse when ``reuse_identical``."""
    name = name.strip()
    if not PROMPT_NAME_RE.match(name):
        raise InvalidError("Nom de prompt invalide : minuscules, chiffres, « _ », « . » ou « - »")
    if not content.strip():
        raise InvalidError("Le contenu du prompt est vide")
    digest = prompt_hash(content)
    latest = await latest_prompt(session, name)
    if latest is not None and latest.content_hash == digest:
        if reuse_identical:
            return latest
        raise ConflictError(
            f"Contenu identique à la dernière version du prompt « {name} » (v{latest.version})"
        )
    prompt = PromptVersion(
        name=name,
        version=(latest.version + 1) if latest else 1,
        content=content,
        description=description.strip(),
        variables=list(variables) if variables is not None else prompt_variables(content),
        content_hash=digest,
        created_by=created_by,
    )
    session.add(prompt)
    await session.flush()
    await audit.record(
        session,
        actor,
        "prompt_version.create",
        "prompt_version",
        prompt.id,
        summary=f"Prompt « {name} » v{prompt.version}",
        details={"name": name, "version": prompt.version, "hash": digest},
    )
    return prompt


async def list_prompts(session: AsyncSession, *, q: str | None = None) -> list[tuple[PromptVersion, int]]:
    """Latest version of every prompt name with its number of versions."""
    conditions: list[Any] = []
    if q and q.strip():
        conditions.append(PromptVersion.name.ilike(f"%{q.strip()}%"))
    latest = list(
        await session.scalars(
            select(PromptVersion)
            .where(*conditions)
            .distinct(PromptVersion.name)
            .order_by(PromptVersion.name, PromptVersion.version.desc())
        )
    )
    counts = dict(
        (
            await session.execute(
                select(PromptVersion.name, func.count()).where(*conditions).group_by(PromptVersion.name)
            )
        ).all()
    )
    return [(p, int(counts.get(p.name, 1))) for p in latest]


async def list_prompt_versions(session: AsyncSession, name: str) -> list[PromptVersion]:
    rows = list(
        await session.scalars(
            select(PromptVersion).where(PromptVersion.name == name).order_by(PromptVersion.version.desc())
        )
    )
    if not rows:
        raise NotFoundError(f"Prompt « {name} » introuvable")
    return rows


def normalize_model(data: dict[str, Any]) -> dict[str, Any]:
    provider = str(data.get("provider") or "").strip()
    model = str(data.get("model") or "").strip()
    if not provider or not model:
        raise InvalidError("La configuration de modèle doit préciser « provider » et « model »")
    normalized = {k: data.get(k) for k in MODEL_FIELDS}
    normalized["provider"], normalized["model"] = provider, model
    normalized["params"] = dict(data.get("params") or {})
    return normalized


def model_dict(model: ModelConfiguration | None) -> dict[str, Any] | None:
    if model is None:
        return None
    return {k: getattr(model, k) for k in MODEL_FIELDS}


async def ensure_model_configuration(
    session: AsyncSession,
    actor: ActorLike,
    data: dict[str, Any],
    *,
    created_by: uuid.UUID | None = None,
) -> tuple[ModelConfiguration, bool]:
    """Content-addressed: returns ``(configuration, created)`` (an identical one is reused)."""
    normalized = normalize_model(data)
    digest = model_configuration_hash(normalized)
    existing = await session.scalar(
        select(ModelConfiguration)
        .where(ModelConfiguration.content_hash == digest)
        .order_by(ModelConfiguration.created_at)
        .limit(1)
    )
    if existing is not None:
        return existing, False
    name = str(data.get("name") or "").strip() or f"{normalized['provider']}/{normalized['model']}"
    model = ModelConfiguration(name=name, content_hash=digest, created_by=created_by, **normalized)
    session.add(model)
    await session.flush()
    await audit.record(
        session,
        actor,
        "model_configuration.create",
        "model_configuration",
        model.id,
        summary=f"Configuration de modèle {name}",
        details={**normalized, "hash": digest},
    )
    return model, True


async def list_model_configurations(
    session: AsyncSession, *, q: str | None = None, offset: int = 0, limit: int = 50
) -> tuple[list[ModelConfiguration], int]:
    conditions: list[Any] = []
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                ModelConfiguration.name.ilike(pattern),
                ModelConfiguration.model.ilike(pattern),
                ModelConfiguration.provider.ilike(pattern),
            )
        )
    total = await session.scalar(select(func.count()).select_from(ModelConfiguration).where(*conditions))
    rows = await session.scalars(
        select(ModelConfiguration)
        .where(*conditions)
        .order_by(ModelConfiguration.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


def normalize_tools(tools: Sequence[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw in enumerate(tools):
        if not isinstance(raw, dict):
            raise InvalidError(f"tools[{index}] : objet {{name, description, parameters}} attendu")
        name = str(raw.get("name") or "").strip()
        if not TOOL_NAME_RE.match(name):
            raise InvalidError(f"tools[{index}] : nom d'outil invalide « {name} »")
        if name in names:
            raise InvalidError(f"tools[{index}] : outil dupliqué « {name} »")
        names.add(name)
        parameters = raw.get("parameters")
        if parameters is None:
            parameters = {"type": "object", "properties": {}}
        if not isinstance(parameters, dict):
            raise InvalidError(f"tools[{index}].parameters : schéma JSON (objet) attendu")
        spec = ToolSpec(name=name, description=str(raw.get("description") or ""), parameters=parameters)
        normalized.append(to_dict(spec))
    return normalized


async def latest_tool_configuration(session: AsyncSession, name: str) -> ToolConfiguration | None:
    return await session.scalar(
        select(ToolConfiguration)
        .where(ToolConfiguration.name == name)
        .order_by(ToolConfiguration.version.desc())
        .limit(1)
    )


async def create_tool_configuration(
    session: AsyncSession,
    actor: ActorLike,
    *,
    name: str,
    tools: Sequence[Any],
    description: str = "",
    created_by: uuid.UUID | None = None,
    reuse_identical: bool = False,
) -> ToolConfiguration:
    name = name.strip()
    if not PROMPT_NAME_RE.match(name):
        raise InvalidError(
            "Nom de configuration d'outils invalide : minuscules, chiffres, « _ », « . » ou « - »"
        )
    normalized = normalize_tools(tools)
    digest = tools_hash(normalized)
    latest = await latest_tool_configuration(session, name)
    if latest is not None and latest.content_hash == digest:
        if reuse_identical:
            return latest
        raise ConflictError(f"Outils identiques à la dernière version de « {name} » (v{latest.version})")
    config = ToolConfiguration(
        name=name,
        version=(latest.version + 1) if latest else 1,
        description=description.strip(),
        tools=normalized,
        content_hash=digest,
        created_by=created_by,
    )
    session.add(config)
    await session.flush()
    await audit.record(
        session,
        actor,
        "tool_configuration.create",
        "tool_configuration",
        config.id,
        summary=f"Outils « {name} » v{config.version} ({len(normalized)} outil(s))",
        details={
            "name": name,
            "version": config.version,
            "tools": [t["name"] for t in normalized],
            "hash": digest,
        },
    )
    return config


async def list_tool_configurations(
    session: AsyncSession, *, name: str | None = None, offset: int = 0, limit: int = 50
) -> tuple[list[ToolConfiguration], int]:
    conditions: list[Any] = []
    if name:
        conditions.append(ToolConfiguration.name == name)
    total = await session.scalar(select(func.count()).select_from(ToolConfiguration).where(*conditions))
    rows = await session.scalars(
        select(ToolConfiguration)
        .where(*conditions)
        .order_by(ToolConfiguration.name, ToolConfiguration.version.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows), int(total or 0)


# =====================================================================================================
# Agent versions
# =====================================================================================================


@dataclass(slots=True)
class VersionBundle:
    """An agent version with its resolved references (for API responses and diffs)."""

    version: AgentVersion
    agent: Agent
    model: ModelConfiguration | None
    prompt: PromptVersion | None
    tools: ToolConfiguration | None
    credential: ProviderCredential | None


async def get_version(session: AsyncSession, version_id: uuid.UUID) -> AgentVersion:
    version = await session.get(AgentVersion, version_id)
    if version is None:
        raise NotFoundError("Version d'agent introuvable")
    return version


async def load_bundle(session: AsyncSession, version: AgentVersion) -> VersionBundle:
    agent = await session.get(Agent, version.agent_id)
    assert agent is not None
    return VersionBundle(
        version=version,
        agent=agent,
        model=await session.get(ModelConfiguration, version.model_configuration_id)
        if version.model_configuration_id
        else None,
        prompt=await session.get(PromptVersion, version.prompt_version_id)
        if version.prompt_version_id
        else None,
        tools=await session.get(ToolConfiguration, version.tool_configuration_id)
        if version.tool_configuration_id
        else None,
        credential=await session.get(ProviderCredential, version.credential_id)
        if version.credential_id
        else None,
    )


async def latest_version(session: AsyncSession, agent_id: uuid.UUID) -> AgentVersion | None:
    return await session.scalar(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version_number.desc())
        .limit(1)
    )


async def list_versions(session: AsyncSession, agent_id: uuid.UUID) -> list[AgentVersion]:
    return list(
        await session.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_number.desc())
        )
    )


def next_version_label(previous: str | None) -> str:
    """Bump the minor number of the previous label: ``1.3`` → ``1.4``, ``2`` → ``2.1``, none → ``1.0``."""
    if not previous:
        return "1.0"
    match = re.match(r"^v?(\d+)(?:\.(\d+))?", previous.strip())
    if not match:
        return f"{previous}.1"
    major, minor = int(match.group(1)), int(match.group(2) or 0)
    return f"{major}.{minor + 1}"


def normalize_budget(budget: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(budget or {})
    unknown = set(data) - {"max_tokens", "max_cost", "max_steps", "timeout_seconds"}
    if unknown:
        raise InvalidError(f"Budget : champ(s) inconnu(s) {', '.join(sorted(unknown))}")
    try:
        spec = from_dict(AgentBudget, data)
    except (TypeError, ValueError) as exc:
        raise InvalidError(f"Budget invalide : {exc}") from exc
    return to_dict(spec)


_DIRECT_FIELDS = (
    "adapter_kind",
    "endpoint",
    "context_config",
    "memory_config",
    "orchestration_config",
    "adapter_config",
    "credential_id",
    "budget",
    "max_concurrency",
    "metadata",
)


def _fields_of(version: AgentVersion) -> dict[str, Any]:
    return {
        "adapter_kind": version.adapter_kind,
        "endpoint": version.endpoint,
        "model_configuration_id": version.model_configuration_id,
        "prompt_version_id": version.prompt_version_id,
        "system_prompt": version.system_prompt,
        "tool_configuration_id": version.tool_configuration_id,
        "context_config": dict(version.context_config or {}),
        "memory_config": dict(version.memory_config or {}),
        "orchestration_config": dict(version.orchestration_config or {}),
        "adapter_config": dict(version.adapter_config or {}),
        "credential_id": version.credential_id,
        "budget": dict(version.budget or {}),
        "max_concurrency": version.max_concurrency,
        "metadata": dict(version.metadata_ or {}),
    }


async def create_version(
    session: AsyncSession,
    actor: ActorLike,
    agent: Agent,
    data: dict[str, Any],
    *,
    created_by: uuid.UUID | None = None,
) -> AgentVersion:
    """Create an immutable version. ``data`` holds only the fields explicitly provided by the caller."""
    if agent.archived:
        raise ConflictError("Agent archivé : désarchivez-le pour créer une version")
    for inline, ref, label in (
        ("model", "model_configuration_id", "modèle"),
        ("system_prompt", "prompt_version_id", "prompt"),
        ("tools", "tool_configuration_id", "outils"),
    ):
        if data.get(inline) is not None and data.get(ref) is not None:
            raise InvalidError(f"Précisez le {label} en ligne ou par référence, pas les deux")
    latest = await latest_version(session, agent.id)
    base: AgentVersion | None = None
    if data.get("base_version_id"):
        base = await session.get(AgentVersion, data["base_version_id"])
        if base is None:
            raise NotFoundError("Version de base introuvable")
        if base.agent_id != agent.id:
            raise InvalidError("La version de base appartient à un autre agent")
    fields: dict[str, Any] = (
        _fields_of(base)
        if base
        else {
            "adapter_kind": None,
            "endpoint": None,
            "model_configuration_id": None,
            "prompt_version_id": None,
            "system_prompt": "",
            "tool_configuration_id": None,
            "context_config": {},
            "memory_config": {},
            "orchestration_config": {},
            "adapter_config": {},
            "credential_id": None,
            "budget": {},
            "max_concurrency": None,
            "metadata": {},
        }
    )
    for key in _DIRECT_FIELDS:
        if key in data:
            value = data[key]
            if key in (
                "context_config",
                "memory_config",
                "orchestration_config",
                "adapter_config",
                "metadata",
            ):
                value = dict(value or {})
            fields[key] = value
    # --- model ---
    model: ModelConfiguration | None = None
    if "model" in data:
        fields["model_configuration_id"] = None
        if data["model"] is not None:
            model, _ = await ensure_model_configuration(
                session, actor, dict(data["model"]), created_by=created_by
            )
            fields["model_configuration_id"] = model.id
    if data.get("model_configuration_id") is not None:
        fields["model_configuration_id"] = data["model_configuration_id"]
    elif "model_configuration_id" in data and "model" not in data:
        fields["model_configuration_id"] = None
    if fields["model_configuration_id"] is not None and model is None:
        model = await session.get(ModelConfiguration, fields["model_configuration_id"])
        if model is None:
            raise NotFoundError("Configuration de modèle introuvable")
    # --- prompt ---
    prompt: PromptVersion | None = None
    if data.get("prompt_version_id") is not None:
        prompt = await session.get(PromptVersion, data["prompt_version_id"])
        if prompt is None:
            raise NotFoundError("Version de prompt introuvable")
    elif data.get("system_prompt") is not None:
        if data.get("prompt_name"):
            prompt = await create_prompt_version(
                session,
                actor,
                name=str(data["prompt_name"]),
                content=str(data["system_prompt"]),
                created_by=created_by,
                reuse_identical=True,
            )
        else:
            fields["prompt_version_id"] = None
            fields["system_prompt"] = str(data["system_prompt"])
    elif data.get("prompt_name"):
        prompt = await latest_prompt(session, str(data["prompt_name"]))
        if prompt is None:
            raise NotFoundError(f"Prompt « {data['prompt_name']} » introuvable")
    if prompt is not None:
        fields["prompt_version_id"] = prompt.id
        fields["system_prompt"] = prompt.content
    # --- tools ---
    tool_config: ToolConfiguration | None = None
    if "tools" in data:
        fields["tool_configuration_id"] = None
        if data["tools"]:
            tool_config = await create_tool_configuration(
                session,
                actor,
                name=str(data.get("tools_name") or f"{agent.slug}-tools"),
                tools=list(data["tools"]),
                created_by=created_by,
                reuse_identical=True,
            )
            fields["tool_configuration_id"] = tool_config.id
    if data.get("tool_configuration_id") is not None:
        fields["tool_configuration_id"] = data["tool_configuration_id"]
    elif "tool_configuration_id" in data and "tools" not in data:
        fields["tool_configuration_id"] = None
    if fields["tool_configuration_id"] is not None and tool_config is None:
        tool_config = await session.get(ToolConfiguration, fields["tool_configuration_id"])
        if tool_config is None:
            raise NotFoundError("Configuration d'outils introuvable")
    # --- checks ---
    if fields["adapter_kind"] is None:
        raise InvalidError("Type d'adapter requis (openai, anthropic, nova, custom_api ou mock)")
    adapter_kind = AdapterKind(fields["adapter_kind"])
    fields["adapter_kind"] = adapter_kind
    if adapter_kind in MODEL_DRIVEN_ADAPTERS and model is None:
        raise InvalidError(f"Une configuration de modèle est requise pour l'adapter {adapter_kind.value}")
    if (
        adapter_kind == AdapterKind.custom_api
        and not (fields["endpoint"] or "").strip()
        and not fields["adapter_config"].get("url")
        and not fields["adapter_config"].get("base_url")
        and fields["credential_id"] is None
    ):
        raise InvalidError("L'adapter custom_api nécessite une URL (endpoint ou adapter_config.url)")
    if (
        fields["credential_id"] is not None
        and await session.get(ProviderCredential, fields["credential_id"]) is None
    ):
        raise NotFoundError("Identifiant fournisseur introuvable")
    if fields["max_concurrency"] is not None and int(fields["max_concurrency"]) < 1:
        raise InvalidError("La concurrence maximale doit être ≥ 1")
    fields["budget"] = normalize_budget(fields["budget"])
    endpoint = (fields["endpoint"] or "").strip() or None
    fields["endpoint"] = endpoint
    tools = list(tool_config.tools) if tool_config else []
    digest = agent_version_hash(
        adapter_kind=adapter_kind.value,
        endpoint=endpoint,
        model=model_dict(model),
        system_prompt=fields["system_prompt"],
        tools=tools,
        context_config=fields["context_config"],
        memory_config=fields["memory_config"],
        orchestration_config=fields["orchestration_config"],
        adapter_config=fields["adapter_config"],
        budget=fields["budget"],
        credential_id=str(fields["credential_id"]) if fields["credential_id"] else None,
    )
    if latest is not None and latest.content_hash == digest:
        raise ConflictError(
            f"Version identique à la dernière version (v{latest.version}) : "
            "aucune modification de comportement"
        )
    label = str(data.get("version") or "").strip() or next_version_label(latest.version if latest else None)
    if not VERSION_LABEL_RE.match(label):
        raise InvalidError("Libellé de version invalide (ex. 1.4)")
    if await session.scalar(
        select(AgentVersion.id).where(AgentVersion.agent_id == agent.id, AgentVersion.version == label)
    ):
        raise ConflictError(f"La version « {label} » existe déjà pour cet agent")
    contamination = await compute_contamination(
        session, system_prompt=fields["system_prompt"], tools=tools, adapter_config=fields["adapter_config"]
    )
    version = AgentVersion(
        agent_id=agent.id,
        version=label,
        version_number=(latest.version_number + 1) if latest else 1,
        adapter_kind=adapter_kind,
        endpoint=endpoint,
        model_configuration_id=fields["model_configuration_id"],
        prompt_version_id=fields["prompt_version_id"],
        system_prompt=fields["system_prompt"],
        tool_configuration_id=fields["tool_configuration_id"],
        context_config=fields["context_config"],
        memory_config=fields["memory_config"],
        orchestration_config=fields["orchestration_config"],
        adapter_config=fields["adapter_config"],
        credential_id=fields["credential_id"],
        budget=fields["budget"],
        max_concurrency=fields["max_concurrency"],
        metadata_=fields["metadata"],
        changelog=str(data.get("changelog") or "").strip(),
        parent_version_id=base.id if base else (latest.id if latest else None),
        contamination=contamination,
        content_hash=digest,
        created_by=created_by,
    )
    session.add(version)
    await session.flush()
    await audit.record(
        session,
        actor,
        "agent_version.create",
        "agent_version",
        version.id,
        summary=f"Nouvelle version {agent.name} v{label}",
        details={
            "agent_id": agent.id,
            "version": label,
            "content_hash": digest,
            "base_version_id": base.id if base else None,
            "contamination_warnings": len(contamination),
        },
    )
    return version


async def compute_contamination(
    session: AsyncSession,
    *,
    system_prompt: str,
    tools: Sequence[dict[str, Any]],
    adapter_config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Contamination warnings of an agent version against every private / fresh scenario version."""
    texts = agent_texts(system_prompt=system_prompt, tools=tools, adapter_config=adapter_config)
    if not texts:
        return []
    rows = (
        await session.execute(
            select(
                Scenario.id,
                Scenario.slug,
                Scenario.visibility,
                ScenarioVersion.canary,
                ScenarioVersion.expected_output,
            )
            .join(ScenarioVersion, ScenarioVersion.scenario_id == Scenario.id)
            .where(Scenario.visibility.in_([ScenarioVisibility.private, ScenarioVisibility.fresh]))
        )
    ).all()
    canaries: list[CanaryRef] = []
    outputs: dict[tuple[str, str], PrivateOutputRef] = {}
    for scenario_id, slug, visibility, canary, expected in rows:
        ref = ScenarioRef(str(scenario_id), slug, ScenarioVisibility(visibility).value)
        if canary:
            canaries.append(CanaryRef(canary, ref))
        if visibility == ScenarioVisibility.private and expected is not None:
            text = flatten_text(expected)
            if text.strip():
                outputs[(ref.scenario_id, text)] = PrivateOutputRef(text, ref)
    return check_contamination(texts, canaries=canaries, private_outputs=list(outputs.values()))


# --- Diff ------------------------------------------------------------------------------------------


def snapshot(bundle: VersionBundle) -> dict[str, Any]:
    v = bundle.version
    return {
        "version": v.version,
        "adapter_kind": v.adapter_kind.value,
        "endpoint": v.endpoint,
        "model": model_dict(bundle.model),
        "prompt": {"name": bundle.prompt.name, "version": bundle.prompt.version} if bundle.prompt else None,
        "system_prompt": v.system_prompt,
        "tools": list(bundle.tools.tools) if bundle.tools else [],
        "tool_configuration": f"{bundle.tools.name}@{bundle.tools.version}" if bundle.tools else None,
        "context_config": dict(v.context_config or {}),
        "memory_config": dict(v.memory_config or {}),
        "orchestration_config": dict(v.orchestration_config or {}),
        "adapter_config": dict(v.adapter_config or {}),
        "credential_id": str(v.credential_id) if v.credential_id else None,
        "budget": dict(v.budget or {}),
        "max_concurrency": v.max_concurrency,
        "metadata": dict(v.metadata_ or {}),
        "changelog": v.changelog,
    }


def _tools_diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, list[str]]:
    old = {t.get("name"): t for t in before}
    new = {t.get("name"): t for t in after}
    return {
        "added": sorted(str(n) for n in new.keys() - old.keys()),
        "removed": sorted(str(n) for n in old.keys() - new.keys()),
        "changed": sorted(str(n) for n in old.keys() & new.keys() if old[n] != new[n]),
    }


def diff_snapshots(
    before: dict[str, Any], after: dict[str, Any], *, labels: tuple[str, str]
) -> dict[str, Any]:
    changes = [
        {"field": key, "before": before.get(key), "after": after.get(key)}
        for key in after
        if key != "version" and before.get(key) != after.get(key)
    ]
    prompt_diff = "".join(
        difflib.unified_diff(
            (before.get("system_prompt") or "").splitlines(keepends=True),
            (after.get("system_prompt") or "").splitlines(keepends=True),
            fromfile=f"v{labels[0]}",
            tofile=f"v{labels[1]}",
        )
    )
    return {
        "changes": changes,
        "prompt_diff": prompt_diff,
        "tools_diff": _tools_diff(before.get("tools") or [], after.get("tools") or []),
    }


async def diff_versions(
    session: AsyncSession, target: AgentVersion, against: AgentVersion | None
) -> dict[str, Any]:
    """Field-level diff of ``target`` against ``against`` (default: its parent / previous version)."""
    if against is None:
        if target.parent_version_id:
            against = await session.get(AgentVersion, target.parent_version_id)
        if against is None:
            against = await session.scalar(
                select(AgentVersion)
                .where(
                    AgentVersion.agent_id == target.agent_id,
                    AgentVersion.version_number < target.version_number,
                )
                .order_by(AgentVersion.version_number.desc())
                .limit(1)
            )
    if against is None:
        raise NotFoundError("Aucune version de référence pour la comparaison")
    before = snapshot(await load_bundle(session, against))
    after = snapshot(await load_bundle(session, target))
    diff = diff_snapshots(before, after, labels=(against.version, target.version))
    return {
        "agent_version_id": target.id,
        "against_version_id": against.id,
        "version": target.version,
        "against_version": against.version,
        "same_content_hash": target.content_hash == against.content_hash,
        **diff,
    }


# --- Credentials usage -------------------------------------------------------------------------------


async def credential_references(session: AsyncSession, credential_id: uuid.UUID) -> tuple[int, int]:
    """``(agent versions, judges)`` referencing a provider credential."""
    versions = await session.scalar(
        select(func.count()).select_from(AgentVersion).where(AgentVersion.credential_id == credential_id)
    )
    judges = await session.scalar(
        select(func.count()).select_from(Judge).where(Judge.credential_id == credential_id)
    )
    return int(versions or 0), int(judges or 0)


async def credential_reference_counts(
    session: AsyncSession, credential_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    if not credential_ids:
        return {}
    versions = dict(
        (
            await session.execute(
                select(AgentVersion.credential_id, func.count())
                .where(AgentVersion.credential_id.in_(credential_ids))
                .group_by(AgentVersion.credential_id)
            )
        ).all()
    )
    judges = dict(
        (
            await session.execute(
                select(Judge.credential_id, func.count())
                .where(Judge.credential_id.in_(credential_ids))
                .group_by(Judge.credential_id)
            )
        ).all()
    )
    return {cid: (int(versions.get(cid, 0)), int(judges.get(cid, 0))) for cid in credential_ids}
