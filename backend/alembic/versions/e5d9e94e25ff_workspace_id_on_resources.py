"""Add nullable workspace_id FK to core resources + backfill from any workspace.

Remaining resources (connections, comments, flows) will land in a follow-up
once scoping semantics are firm. For now we cover the two entry points —
model_objects and diagrams — so new writes can stamp workspace_id immediately.

Revision ID: e5d9e94e25ff
Revises: 9e93425c2400
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5d9e94e25ff'
down_revision: Union[str, Sequence[str], None] = '9e93425c2400'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ('model_objects', 'diagrams'):
        op.add_column(table, sa.Column('workspace_id', sa.UUID(), nullable=True))
        op.create_foreign_key(
            f'fk_{table}_workspace_id',
            table, 'workspaces',
            ['workspace_id'], ['id'],
            ondelete='SET NULL',
        )
        op.create_index(f'ix_{table}_workspace_id', table, ['workspace_id'])

    # Backfill any existing rows to the oldest workspace in the system.
    # Production deploys with real users should re-run this per-user before
    # enabling scope enforcement.
    op.execute(
        """
        WITH first_ws AS (SELECT id FROM workspaces ORDER BY created_at LIMIT 1)
        UPDATE model_objects SET workspace_id = (SELECT id FROM first_ws)
        WHERE workspace_id IS NULL
        """
    )
    op.execute(
        """
        WITH first_ws AS (SELECT id FROM workspaces ORDER BY created_at LIMIT 1)
        UPDATE diagrams SET workspace_id = (SELECT id FROM first_ws)
        WHERE workspace_id IS NULL
        """
    )


def downgrade() -> None:
    for table in ('model_objects', 'diagrams'):
        op.drop_index(f'ix_{table}_workspace_id', table_name=table)
        op.drop_constraint(f'fk_{table}_workspace_id', table, type_='foreignkey')
        op.drop_column(table, 'workspace_id')
