"""observed runs: origin `observed` and idempotency key `external_id`

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-09 09:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('evaluation_runs', sa.Column('external_id', sa.Text(), nullable=True))
    op.create_index(
        'uq_evaluation_runs_agent_external_id',
        'evaluation_runs',
        ['agent_id', 'external_id'],
        unique=True,
        postgresql_where=sa.text('external_id IS NOT NULL'),
    )
    op.drop_constraint(op.f('ck_evaluation_runs_origin'), 'evaluation_runs', type_='check')
    op.create_check_constraint(
        op.f('ck_evaluation_runs_origin'),
        'evaluation_runs',
        "origin IN ('adhoc', 'benchmark', 'experiment', 'observed')",
    )


def downgrade() -> None:
    # Observed runs cannot exist under the old constraint: they are removed (cascades to their trace,
    # events, evaluations and scores).
    op.execute("DELETE FROM evaluation_runs WHERE origin = 'observed'")
    op.drop_constraint(op.f('ck_evaluation_runs_origin'), 'evaluation_runs', type_='check')
    op.create_check_constraint(
        op.f('ck_evaluation_runs_origin'),
        'evaluation_runs',
        "origin IN ('adhoc', 'benchmark', 'experiment')",
    )
    op.drop_index('uq_evaluation_runs_agent_external_id', table_name='evaluation_runs')
    op.drop_column('evaluation_runs', 'external_id')
