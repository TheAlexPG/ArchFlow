"""add position to comments

Revision ID: ac3d7e1f9b20
Revises: 68d25cb8444b
Create Date: 2026-04-16 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ac3d7e1f9b20'
down_revision: Union[str, Sequence[str], None] = '68d25cb8444b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('comments', sa.Column('position_x', sa.Float(), nullable=True))
    op.add_column('comments', sa.Column('position_y', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('comments', 'position_y')
    op.drop_column('comments', 'position_x')
