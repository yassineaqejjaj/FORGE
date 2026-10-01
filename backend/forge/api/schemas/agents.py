"""Agent Registry schemas (``/agents``, ``/agent-versions``, ``/prompts``, ``/model-configurations``,
``/tool-configurations``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from forge.api.schemas.common import ApiModel
from forge.domain.enums import AdapterKind

# --- Agents ------------------------------------------------------------------------------------------


class AgentCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=80, description="Généré depuis le nom si absent")
    description: str = Field(default="", max_length=5000)
    provider: str = Field(
        default="", max_length=200, description="Organisation ou produit fournissant l'agent"
    )
    tags: list[str] = Field(default_factory=list, max_length=50)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdateIn(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    provider: str | None = Field(default=None, max_length=200)
    tags: list[str] | None = Field(default=None, max_length=50)
    metadata: dict[str, Any] | None = None
    archived: bool | None = None


class AgentVersionSummary(ApiModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version: str
    version_number: int
    adapter_kind: AdapterKind
    model: str | None = None
    content_hash: str
    changelog: str
    contamination_warnings: int = 0
    parent_version_id: uuid.UUID | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime


class AgentOut(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str
    provider: str
    tags: list[str]
    metadata: dict[str, Any]
    archived: bool
    owner_id: uuid.UUID | None = None
    versions_count: int = 0
    latest_version: AgentVersionSummary | None = None
    created_at: datetime
    updated_at: datetime


# --- Configurations ----------------------------------------------------------------------------------


class ModelConfigIn(ApiModel):
    name: str | None = Field(default=None, max_length=200)
    provider: str = Field(
        min_length=1, max_length=100, description="openai, anthropic, mistral, ollama, nova…"
    )
    model: str = Field(min_length=1, max_length=200)
    model_version: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    seed: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    input_cost_per_mtok: float | None = Field(
        default=None, ge=0, description="Coût par million de tokens d'entrée"
    )
    output_cost_per_mtok: float | None = Field(default=None, ge=0)


class ModelConfigOut(ApiModel):
    id: uuid.UUID
    name: str
    provider: str
    model: str
    model_version: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    seed: int | None = None
    params: dict[str, Any]
    input_cost_per_mtok: float | None = None
    output_cost_per_mtok: float | None = None
    content_hash: str
    created_by: uuid.UUID | None = None
    created_at: datetime


class ToolIn(ApiModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=5000)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


class ToolConfigCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    tools: list[ToolIn] = Field(min_length=1, max_length=128)


class ToolConfigOut(ApiModel):
    id: uuid.UUID
    name: str
    version: int
    description: str
    tools: list[dict[str, Any]]
    content_hash: str
    created_by: uuid.UUID | None = None
    created_at: datetime


class PromptCreateIn(ApiModel):
    name: str = Field(min_length=1, max_length=100, description="Ex. product_manager")
    content: str = Field(min_length=1, max_length=200_000)
    description: str = Field(default="", max_length=2000)
    variables: list[str] | None = Field(default=None, description="Détectées ({{variable}}) si absentes")


class PromptVersionOut(ApiModel):
    id: uuid.UUID
    name: str
    version: int
    content: str
    description: str
    variables: list[str]
    content_hash: str
    created_by: uuid.UUID | None = None
    created_at: datetime


class PromptSummaryOut(ApiModel):
    name: str
    latest_version: int
    versions_count: int
    latest_version_id: uuid.UUID
    description: str
    content_hash: str
    updated_at: datetime


# --- Versions ----------------------------------------------------------------------------------------


class BudgetIn(ApiModel):
    max_tokens: int | None = Field(default=None, ge=1)
    max_cost: float | None = Field(default=None, ge=0)
    max_steps: int = Field(default=8, ge=1, le=100)
    timeout_seconds: float = Field(default=120.0, gt=0, le=3600)


class AgentVersionCreateIn(ApiModel):
    """Every field is optional with ``base_version_id`` (improvement loop: only overrides are given)."""

    version: str | None = Field(default=None, max_length=40, description="Libellé (auto : mineure suivante)")
    base_version_id: uuid.UUID | None = Field(default=None, description="Version de départ (champs repris)")
    adapter_kind: AdapterKind | None = None
    endpoint: str | None = Field(default=None, max_length=2000)
    model: ModelConfigIn | None = Field(default=None, description="Configuration de modèle en ligne")
    model_configuration_id: uuid.UUID | None = None
    prompt_version_id: uuid.UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=200_000)
    prompt_name: str | None = Field(
        default=None, max_length=100, description="Avec system_prompt : crée la version suivante de ce prompt"
    )
    tools: list[ToolIn] | None = Field(default=None, max_length=128, description="Outils en ligne")
    tools_name: str | None = Field(
        default=None, max_length=100, description="Nom de la configuration d'outils"
    )
    tool_configuration_id: uuid.UUID | None = None
    context_config: dict[str, Any] | None = None
    memory_config: dict[str, Any] | None = None
    orchestration_config: dict[str, Any] | None = None
    adapter_config: dict[str, Any] | None = None
    credential_id: uuid.UUID | None = None
    budget: BudgetIn | None = None
    max_concurrency: int | None = Field(default=None, ge=1, le=1000)
    metadata: dict[str, Any] | None = None
    changelog: str = Field(default="", max_length=10_000)


class PromptRef(ApiModel):
    id: uuid.UUID
    name: str
    version: int


class ToolConfigRef(ApiModel):
    id: uuid.UUID
    name: str
    version: int


class CredentialRef(ApiModel):
    id: uuid.UUID
    name: str
    kind: str
    secret_hint: str | None = None


class AgentVersionOut(ApiModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    agent_slug: str
    version: str
    version_number: int
    label: str
    adapter_kind: AdapterKind
    endpoint: str | None = None
    model_configuration: ModelConfigOut | None = None
    prompt: PromptRef | None = None
    system_prompt: str
    tool_configuration: ToolConfigRef | None = None
    tools: list[dict[str, Any]]
    context_config: dict[str, Any]
    memory_config: dict[str, Any]
    orchestration_config: dict[str, Any]
    adapter_config: dict[str, Any]
    credential: CredentialRef | None = None
    budget: dict[str, Any]
    max_concurrency: int | None = None
    metadata: dict[str, Any]
    changelog: str
    parent_version_id: uuid.UUID | None = None
    contamination: list[dict[str, Any]]
    content_hash: str
    created_by: uuid.UUID | None = None
    created_at: datetime


class FieldChange(ApiModel):
    field: str
    before: Any = None
    after: Any = None


class ToolsDiff(ApiModel):
    added: list[str]
    removed: list[str]
    changed: list[str]


class AgentVersionDiffOut(ApiModel):
    agent_version_id: uuid.UUID
    against_version_id: uuid.UUID
    version: str
    against_version: str
    same_content_hash: bool
    changes: list[FieldChange]
    prompt_diff: str
    tools_diff: ToolsDiff


class AgentTestIn(ApiModel):
    input: dict[str, Any] = Field(description='Entrée de l\'agent : {"prompt": …} ou {"messages": […]}')
    context: dict[str, Any] | None = None


class AgentTestOut(ApiModel):
    agent_version_id: uuid.UUID
    output_text: str | None = None
    output_json: Any = None
    result: dict[str, Any] = Field(default_factory=dict)
