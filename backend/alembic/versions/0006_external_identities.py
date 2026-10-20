"""OIDC identity links (NOV-108): external_identities (issuer, sub) -> user

Additive: one new table (and its foreign key to ``users``), nothing existing changes. Idempotent.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-16 12:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS external_identities (
            issuer text NOT NULL,
            sub text NOT NULL,
            user_id uuid NOT NULL,
            linked_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT pk_external_identities PRIMARY KEY (issuer, sub),
            CONSTRAINT fk_external_identities_user_id_users FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        'CREATE UNIQUE INDEX IF NOT EXISTS uq_external_identities_issuer_user_id '
        'ON external_identities (issuer, user_id)'
    )
    op.execute('CREATE INDEX IF NOT EXISTS ix_external_identities_user_id ON external_identities (user_id)')


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS external_identities')
