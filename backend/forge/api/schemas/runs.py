"""Evaluation run schemas (``/runs``)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from forge.api.schemas.common import ApiModel
from forge.api.schemas.traces import ProtocolEventIn
from forge.domain.enums import ExperimentArm, RunOrigin, RunStatus


def _bounded_manifest(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is not None and len(json.dumps(value, default=str)) > 20_000:
        raise ValueError("le manifeste dépasse 20 000 caractères")
    return value


class RunCreateIn(ApiModel):
    agent_version_id: uuid.UUID
    scenario_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=500, description="Dernière version"
    )
    scenario_version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)
    repetitions: int = Field(default=1, ge=1, le=20)
    evaluation_config_id: uuid.UUID | None = Field(
        default=None, description="Configuration par défaut si absente"
    )
    tags: list[str] = Field(default_factory=list, max_length=20)
    context_snapshot_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description="Snapshot ORBIT de l'exécution d'origine (« nom@vN »)",
    )
    release_id: str | None = Field(default=None, min_length=1, max_length=200)
    manifest: dict[str, Any] | None = Field(
        default=None, description="Manifeste de l'exécution d'origine (NOVA : `run_manifest`), gardé tel quel"
    )

    @field_validator("manifest")
    @classmethod
    def _bound_manifest(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _bounded_manifest(value)


class ObservedUsageIn(ApiModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)


MAX_OBSERVED_EVENTS = 300


class ObservedRunIn(ApiModel):
    """A run already executed by an external system (docs/OBSERVED_RUNS.md): FORGE only evaluates it."""

    agent_version_id: uuid.UUID
    scenario_id: uuid.UUID = Field(description="La version courante du scénario est utilisée")
    evaluation_config_id: uuid.UUID | None = Field(
        default=None, description="Configuration par défaut (celle des runs ad hoc) si absente"
    )
    input: dict[str, Any] = Field(
        description='Ce qui a été demandé à l\'agent : {"prompt": …, "context": {…}}'
    )
    output_text: str | None = Field(default=None, description="Résumé lisible de ce qui a été produit")
    output_json: dict[str, Any] | None = Field(
        default=None, description="Résultat structuré, lu par les règles du scénario (chemins JSON)"
    )
    execution_status: Literal["completed", "failed"]
    error: str | None = Field(default=None, max_length=4000, description="Cause de l'échec (si failed)")
    started_at: AwareDatetime
    completed_at: AwareDatetime
    usage: ObservedUsageIn = Field(default_factory=ObservedUsageIn)
    tags: list[str] = Field(default_factory=list, max_length=20)
    external_id: str = Field(
        min_length=1,
        max_length=200,
        description="Clé d'idempotence (ex. « nova-sdlc:<uuid> ») : unique par agent",
    )
    context_snapshot_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=300,
        description="Snapshot ORBIT utilisé par l'agent (« nom@vN »). Déduit de `manifest` si absent",
    )
    release_id: str | None = Field(
        default=None, min_length=1, max_length=200, description="Release de l'agent qui a produit ce run"
    )
    manifest: dict[str, Any] | None = Field(
        default=None,
        description="Manifeste du run côté système externe (NOVA : `run_manifest`), conservé tel quel",
    )

    events: list[ProtocolEventIn] = Field(
        default_factory=list,
        max_length=MAX_OBSERVED_EVENTS,
        description=(
            "Étapes du run (outils, modèle, récupérations de contexte…) au format Agent Protocol. "
            "`run_started`, `final_answer`, `run_completed` et `error` sont écrits par FORGE et ignorés ici."
        ),
    )

    @field_validator("manifest")
    @classmethod
    def _bound_manifest(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _bounded_manifest(value)

    @field_validator("external_id")
    @classmethod
    def _strip_external_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("la clé d'idempotence ne doit pas être vide")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.completed_at < self.started_at:
            raise ValueError("completed_at doit être postérieur ou égal à started_at")
        if self.execution_status == "completed" and self.error:
            raise ValueError("« error » n'est accepté que pour un run en échec (execution_status = failed)")
        return self


class RunOut(ApiModel):
    id: uuid.UUID
    status: RunStatus
    status_detail: str | None = None
    origin: RunOrigin
    arm: ExperimentArm | None = None
    repetition: int
    tags: list[str]
    external_id: str | None = Field(default=None, description="Clé d'idempotence (runs observés)")
    context_snapshot_id: str | None = Field(default=None, description="Snapshot ORBIT (« nom@vN »)")
    release_id: str | None = Field(default=None, description="Release de l'agent")
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    scenario_slug: str
    scenario_name: str
    scenario_version: int | None = None
    category: str
    difficulty: str | None = None
    visibility: str
    classification: int
    agent_id: uuid.UUID
    agent_version_id: uuid.UUID
    agent_name: str | None = None
    agent_version: str | None = None
    agent_label: str | None = None
    model: str | None = None
    evaluation_config_id: uuid.UUID
    evaluation_round: int
    composite_score: float | None = None
    passed: bool | None = None
    gate_failed: bool
    error_type: str | None = None
    latency_ms: float | None = None
    cost: float | None = None
    total_tokens: int | None = None
    benchmark_execution_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunScenarioOut(ApiModel):
    id: uuid.UUID
    version_id: uuid.UUID
    slug: str
    name: str
    version: int | None = None
    category: str
    difficulty: str | None = None
    visibility: str
    classification: int
    classification_warning: str | None = None
    family_id: str | None = None
    variant_label: str | None = None
    tags: list[str] = Field(default_factory=list)
    content: dict[str, Any] = Field(
        description="Contenu du scénario figé dans le manifeste (masqué si privé)"
    )


class RunCompositeOut(ApiModel):
    round: int
    value: float
    raw_value: float
    passed: bool
    gate_failed: bool
    dimensions: list[dict[str, Any]]
    gates: list[dict[str, Any]]
    missing_dimensions: list[str]
    formula: str


class RunCountsOut(ApiModel):
    evaluations: int
    errors: int
    human_evaluations: int


class RunDetailOut(ApiModel):
    id: uuid.UUID
    status: RunStatus
    status_detail: str | None = None
    origin: RunOrigin
    arm: ExperimentArm | None = None
    repetition: int
    tags: list[str]
    external_id: str | None = None
    context_snapshot_id: str | None = None
    release_id: str | None = None
    source_manifest: dict[str, Any] | None = None
    error: str | None = None
    error_type: str | None = None
    otel_trace_id: str
    manifest_hash: str
    evaluation_round: int
    composite_score: float | None = None
    passed: bool | None = None
    gate_failed: bool
    created_by: uuid.UUID | None = None
    created_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    executed_at: datetime | None = None
    evaluated_at: datetime | None = None
    finished_at: datetime | None = None
    redacted: bool
    scenario: RunScenarioOut
    agent: dict[str, Any]
    evaluation_config: dict[str, Any]
    trace: dict[str, Any] | None = None
    composite: RunCompositeOut | None = None
    counts: RunCountsOut
    feedback_report_id: uuid.UUID | None = None
    benchmark_execution_id: uuid.UUID | None = None
    benchmark_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    experiment_name: str | None = None


class RunTraceOut(ApiModel):
    run_id: uuid.UUID
    status: RunStatus
    redacted: bool
    trace: dict[str, Any] | None = None
    events: list[dict[str, Any]]
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    model_calls: list[dict[str, Any]]


class RunManifestOut(ApiModel):
    run_id: str
    manifest_hash: str
    redacted: bool
    manifest: dict[str, Any]


class ContextGapIn(ApiModel):
    """Combler le manque de contexte d'un run via ORBIT (docs/OBSERVED_RUNS.md §ORION)."""

    missing: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Informations manquantes (défaut : les erreurs MISSING_INFORMATION du run)",
    )
    orbit_project: str | None = Field(
        default=None,
        max_length=120,
        description="Projet ORBIT, si ni la configuration de l'agent ni le run ne l'indiquent",
    )
    credential_id: uuid.UUID | None = Field(
        default=None, description="Identifiants ORBIT (défaut : ceux de l'agent)"
    )
    snapshot: str | None = Field(
        default=None,
        max_length=120,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._\-]*$",
        description="Snapshot où ORBIT enregistre le résultat (défaut : version suivante de celui du run)",
    )
    retest: bool = Field(
        default=False, description="Crée une version d'agent épinglée sur le nouveau snapshot et la relance"
    )


class ContextGapOut(ApiModel):
    run_id: uuid.UUID
    missing: list[str]
    orbit_request_id: str
    orbit_project: str
    completion: dict[str, Any] = Field(
        description="Réponse d'ORBIT : nouveau snapshot, éléments ajoutés, manques restants"
    )
    candidate_version_id: uuid.UUID | None = None
    retest_run_id: uuid.UUID | None = None


class PromoteRunIn(ApiModel):
    label: str | None = Field(
        default=None, max_length=60, description="Suffixe du scénario (défaut : regression-<id du run>)"
    )


class PromoteRunOut(ApiModel):
    scenario_id: uuid.UUID
    scenario_version_id: uuid.UUID
    slug: str
    created: bool = Field(description="Faux si ce run avait déjà été promu (même scénario renvoyé)")


class RiskSignalOut(ApiModel):
    kind: str = Field(
        description="tool_loop, tool_errors, error_events, slow, token_overrun, *_budget, timeout"
    )
    message: str
    weight: float


class RunRiskOut(ApiModel):
    run_id: uuid.UUID
    run_status: str
    level: str = Field(description="low | medium | high")
    score: float = Field(description="0–1 ; combine les signaux indépendants")
    finished: bool = Field(description="Le run est terminé : le risque ne concerne plus qu'un run en cours")
    signals: list[RiskSignalOut]
    observed: dict[str, int] = Field(
        description="Ce qui a été observé : événements, appels d'outils, tokens, durée"
    )
    reference_runs: int = Field(description="Runs réussis de la même version servant de référence")
