"""ORION workspace / project model (NOV-105): workspaces, projects, memberships, workspace_id columns

Additive and reversible. Nothing existing is rewritten:

* ``workspace_id uuid NOT NULL DEFAULT '<default workspace>'`` is a metadata-only ``ADD COLUMN`` (constant
  default, PostgreSQL >= 11): no table rewrite, no per-row work, whatever the table size. ``project_id``
  is a nullable column (also metadata-only);
* foreign keys are added ``NOT VALID`` (no scan, short lock) and validated afterwards with
  ``VALIDATE CONSTRAINT`` (``SHARE UPDATE EXCLUSIVE``: reads and writes continue);
* indexes are built ``CONCURRENTLY`` (no write lock);
* every statement runs in autocommit, so an ``ACCESS EXCLUSIVE`` lock is held for one statement only, with a
  ``lock_timeout`` (a busy table fails the migration fast instead of queueing every query behind it).
  Every step is idempotent: re-running after a failure resumes where it stopped.

Downgrade drops the new columns, indexes and tables (the workspace assignment of rows is lost, the content
is untouched).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Fixed (documented in docs/WORKSPACES.md): ``forge.infra.models.workspace.ORION_DEFAULT_WORKSPACE_ID``.
DEFAULT_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"
MIGRATION_LOCK_ID = 0x464F52474535  # session-level advisory lock serialising concurrent upgrades
LOCK_TIMEOUT = "10s"

#: Tables with ``workspace_id`` and the optional ``project_id``.
PROJECT_TABLES = (
    "agents",
    "api_keys",
    "provider_credentials",
    "datasets",
    "scenarios",
    "benchmarks",
    "experiments",
    "evaluation_runs",
    "judges",
    "evaluation_configs",
)
#: Tables with ``workspace_id`` only (children of the above or immutable registries).
WORKSPACE_TABLES = (
    "model_configurations",
    "prompt_versions",
    "tool_configurations",
    "agent_versions",
    "audit_events",
    "dataset_items",
    "scenario_versions",
    "benchmark_executions",
    "execution_traces",
    "trace_events",
    "evaluations",
    "scores",
    "composite_scores",
    "run_errors",
    "feedback_reports",
    "judge_cache",
    "jobs",
)
ALL_TABLES = PROJECT_TABLES + WORKSPACE_TABLES

#: ``(index name, table, columns)`` — the workspace-leading indexes of the main listing queries.
WORKSPACE_INDEXES = (
    ("ix_agents_workspace_id_created_at", "agents", "workspace_id, created_at"),
    ("ix_scenarios_workspace_id_created_at", "scenarios", "workspace_id, created_at"),
    ("ix_datasets_workspace_id_created_at", "datasets", "workspace_id, created_at"),
    ("ix_benchmarks_workspace_id_created_at", "benchmarks", "workspace_id, created_at"),
    ("ix_experiments_workspace_id_created_at", "experiments", "workspace_id, created_at"),
    ("ix_evaluation_runs_workspace_id_created_at", "evaluation_runs", "workspace_id, created_at"),
    ("ix_api_keys_workspace_id", "api_keys", "workspace_id"),
    ("ix_provider_credentials_workspace_id", "provider_credentials", "workspace_id"),
    ("ix_judges_workspace_id_key_is_latest", "judges", "workspace_id, key, is_latest"),
    (
        "ix_evaluation_configs_workspace_id_key_is_latest",
        "evaluation_configs",
        "workspace_id, key, is_latest",
    ),
    ("ix_audit_events_workspace_id_created_at", "audit_events", "workspace_id, created_at"),
)
#: Partial indexes on the (mostly ``NULL``) project column of the main resources.
PROJECT_INDEXES = tuple(
    (f"ix_{table}_project_id", table, "project_id")
    for table in ("agents", "scenarios", "datasets", "benchmarks", "experiments", "evaluation_runs")
)


def _fk_name(table: str, column: str, referred: str) -> str:
    return f"fk_{table}_{column}_{referred}"


def _add_fk(table: str, column: str, referred: str) -> None:
    name = _fk_name(table, column, referred)
    op.execute(
        f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}'
                           AND conrelid = '{table}'::regclass) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column})
                    REFERENCES {referred} (id) ON DELETE RESTRICT NOT VALID;
            END IF;
        END $$
        """
    )


def _validate_fk(table: str, column: str, referred: str) -> None:
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {_fk_name(table, column, referred)}")


def _create_index(name: str, table: str, columns: str, where: str | None = None) -> None:
    bind = op.get_bind()
    invalid = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name AND NOT i.indisvalid"
        ),
        {"name": name},
    ).first()
    if invalid:  # left by a cancelled CONCURRENTLY build
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    suffix = f" WHERE {where}" if where else ""
    op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} ({columns}){suffix}")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("SELECT pg_advisory_lock(:id)").bindparams(id=MIGRATION_LOCK_ID))
        try:
            _upgrade()
        finally:
            op.execute(sa.text("SELECT pg_advisory_unlock(:id)").bindparams(id=MIGRATION_LOCK_ID))


def _upgrade() -> None:
    op.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")

    # 1. New tables ------------------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspaces (
            id uuid NOT NULL,
            slug text NOT NULL,
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_workspaces PRIMARY KEY (id)
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_slug ON workspaces (slug)")
    op.execute(
        f"""
        INSERT INTO workspaces (id, slug, name)
        VALUES ('{DEFAULT_WORKSPACE_ID}', 'default', 'Espace par défaut')
        ON CONFLICT (id) DO NOTHING
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            slug text NOT NULL,
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_projects PRIMARY KEY (id),
            CONSTRAINT uq_projects_workspace_id_slug UNIQUE (workspace_id, slug),
            CONSTRAINT fk_projects_workspace_id_workspaces FOREIGN KEY (workspace_id)
                REFERENCES workspaces (id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_members (
            user_id uuid NOT NULL,
            workspace_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_workspace_members PRIMARY KEY (user_id),
            CONSTRAINT fk_workspace_members_user_id_users FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE,
            CONSTRAINT fk_workspace_members_workspace_id_workspaces FOREIGN KEY (workspace_id)
                REFERENCES workspaces (id) ON DELETE RESTRICT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workspace_members_workspace_id ON workspace_members (workspace_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS project_members (
            project_id uuid NOT NULL,
            user_id uuid NOT NULL,
            role text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_project_members PRIMARY KEY (project_id, user_id),
            CONSTRAINT ck_project_members_role CHECK (role IN
                ('viewer', 'evaluator', 'editor', 'maintainer', 'admin')),
            CONSTRAINT fk_project_members_project_id_projects FOREIGN KEY (project_id)
                REFERENCES projects (id) ON DELETE CASCADE,
            CONSTRAINT fk_project_members_user_id_users FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_project_members_user_id ON project_members (user_id)")

    # 2. Columns: metadata-only (constant default / NULL) -----------------------------------------
    for table in ALL_TABLES:
        project = ", ADD COLUMN IF NOT EXISTS project_id uuid" if table in PROJECT_TABLES else ""
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS workspace_id uuid NOT NULL "
            f"DEFAULT '{DEFAULT_WORKSPACE_ID}'{project}"
        )

    # 3. Existing users belong to the default workspace (explicit rows; the absence of a row means the same).
    op.execute(
        f"""
        INSERT INTO workspace_members (user_id, workspace_id)
        SELECT id, '{DEFAULT_WORKSPACE_ID}' FROM users
        ON CONFLICT (user_id) DO NOTHING
        """
    )

    # 4. Foreign keys: NOT VALID (no scan), then validated without blocking writes.
    for table in ALL_TABLES:
        _add_fk(table, "workspace_id", "workspaces")
        if table in PROJECT_TABLES:
            _add_fk(table, "project_id", "projects")
    op.execute("RESET lock_timeout")
    for table in ALL_TABLES:
        _validate_fk(table, "workspace_id", "workspaces")
        if table in PROJECT_TABLES:
            _validate_fk(table, "project_id", "projects")

    # 5. Indexes, built concurrently --------------------------------------------------------------
    for name, table, columns in WORKSPACE_INDEXES:
        _create_index(name, table, columns)
    for name, table, columns in PROJECT_INDEXES:
        _create_index(name, table, columns, where="project_id IS NOT NULL")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(sa.text("SELECT pg_advisory_lock(:id)").bindparams(id=MIGRATION_LOCK_ID))
        try:
            _downgrade()
        finally:
            op.execute(sa.text("SELECT pg_advisory_unlock(:id)").bindparams(id=MIGRATION_LOCK_ID))


def _downgrade() -> None:
    op.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
    for table in ALL_TABLES:
        project = ", DROP COLUMN IF EXISTS project_id" if table in PROJECT_TABLES else ""
        # Dropping the columns drops their foreign keys and indexes with them.
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS workspace_id{project}")
    op.execute("DROP TABLE IF EXISTS project_members")
    op.execute("DROP TABLE IF EXISTS workspace_members")
    op.execute("DROP TABLE IF EXISTS projects")
    op.execute("DROP TABLE IF EXISTS workspaces")
    op.execute("RESET lock_timeout")
