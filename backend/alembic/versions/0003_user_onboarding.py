"""users.onboarded_at: first-login welcome tour

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0003'
down_revision: str | None = '0002'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('users', sa.Column('onboarded_at', sa.DateTime(timezone=True), nullable=True))
    # Existing accounts already know the platform: only accounts created from now on get the tour.
    op.execute('UPDATE users SET onboarded_at = now()')


def downgrade() -> None:
    op.drop_column('users', 'onboarded_at')
