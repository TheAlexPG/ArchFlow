"""workspace_invites.team_ids — teams to auto-join on invite acceptance

Revision ID: 7a9f7916de28
Revises: 648de0788239
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a9f7916de28'
down_revision: Union[str, Sequence[str], None] = '648de0788239'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'workspace_invites',
        sa.Column(
            'team_ids',
            sa.ARRAY(sa.UUID()),
            nullable=False,
            server_default=sa.text("'{}'::uuid[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column('workspace_invites', 'team_ids')
