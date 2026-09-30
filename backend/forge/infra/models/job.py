"""Job queue (Postgres, ``SELECT … FOR UPDATE SKIP LOCKED``) with two logical queues.

``execution`` jobs call agents (slow, rate limited); ``evaluation`` jobs run rules, judges,
aggregation. Workers subscribe to one or both queues (``FORGE_WORKER_QUEUES``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from forge.domain.enums import JobKind, JobQueue, JobStatus
from forge.infra.db import Base, CreatedAtMixin, UUIDPkMixin, utcnow
from forge.infra.models._types import StrEnumType, enum_check


class Job(UUIDPkMixin, CreatedAtMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        enum_check("kind", JobKind),
        enum_check("queue", JobQueue),
        enum_check("status", JobStatus),
        Index("ix_jobs_claim", "queue", "status", "priority", "run_after"),
        Index("ix_jobs_run_id", "run_id"),
        # At most one active job per dedupe key (finalize jobs are enqueued by many runs).
        Index(
            "uq_jobs_active_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
        ),
    )

    kind: Mapped[JobKind] = mapped_column(StrEnumType(JobKind), nullable=False)
    queue: Mapped[JobQueue] = mapped_column(StrEnumType(JobQueue), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        StrEnumType(JobStatus), nullable=False, default=JobStatus.queued, server_default=text("'queued'")
    )
    #: Higher first. Ad-hoc runs (UI) are prioritised over large benchmark matrices.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default=text("3"))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=True
    )
    dedupe_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
