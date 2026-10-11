"""ORION links on runs: context snapshot, release and the reporter's run manifest

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-11 09:30:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0004'
down_revision: str | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('evaluation_runs', sa.Column('context_snapshot_id', sa.Text(), nullable=True))
    op.add_column('evaluation_runs', sa.Column('release_id', sa.Text(), nullable=True))
    op.add_column('evaluation_runs', sa.Column('source_manifest', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index('ix_evaluation_runs_context_snapshot_id', 'evaluation_runs', ['context_snapshot_id'])
    op.create_index('ix_evaluation_runs_release_id', 'evaluation_runs', ['release_id'])


def downgrade() -> None:
    op.drop_index('ix_evaluation_runs_release_id', table_name='evaluation_runs')
    op.drop_index('ix_evaluation_runs_context_snapshot_id', table_name='evaluation_runs')
    op.drop_column('evaluation_runs', 'source_manifest')
    op.drop_column('evaluation_runs', 'release_id')
    op.drop_column('evaluation_runs', 'context_snapshot_id')
