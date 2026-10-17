"""Per-account migration flags (NOV-113): account_flags

Additive: one new table (and its foreign key to ``users``), nothing existing changes. Idempotent.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-16 15:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = '0007'
down_revision: str | None = '0006'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_flags (
            user_id uuid NOT NULL,
            password_login_disabled boolean NOT NULL DEFAULT false,
            sso_required boolean NOT NULL DEFAULT false,
            break_glass boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now(),
            updated_by text,
            CONSTRAINT pk_account_flags PRIMARY KEY (user_id),
            CONSTRAINT fk_account_flags_user_id_users FOREIGN KEY (user_id)
                REFERENCES users (id) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute('DROP TABLE IF EXISTS account_flags')
