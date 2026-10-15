"""Schemas of the forget endpoint and of the signed ORBIT webhook."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from forge.api.schemas.common import ApiModel


class ForgetIn(ApiModel):
    document_ids: list[str] = Field(default_factory=list, max_length=200, description="`document_id` ORBIT")
    memory_item_ids: list[str] = Field(
        default_factory=list, max_length=200, description="`memory_item_id` ORBIT"
    )
    lineage_ids: list[str] = Field(
        default_factory=list, max_length=200, description="Lignée de mémoire ORBIT"
    )
    task_ids: list[str] = Field(
        default_factory=list, max_length=200, description="Tâche NOVA (`external_id` = « …:<task_id> »)"
    )
    reason: str = Field(default="", max_length=300)


class ForgetOut(ApiModel):
    processed_at: datetime
    source: str
    runs: int = Field(description="Runs dont les copies ont été vidées")
    traces: int
    trace_events: int
    evaluations: int
    scenario_versions: int
    manifests: int
    feedback_reports: int
    judge_cache_entries: int
    nothing_matched: bool = Field(description="Aucune copie trouvée (déjà oublié, ou jamais reçu)")


class WebhookAck(ApiModel):
    handled: bool
    event: str
    receipt: ForgetOut | None = None
