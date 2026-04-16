"""add pinned to diagrams

Revision ID: c7e4a8d12f91
Revises: 37cbc503fe13
Create Date: 2026-04-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c7e4a8d12f91'
down_revision: Union[str, Sequence[str], None] = '37cbc503fe13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('diagrams', sa.Column('pinned', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('diagrams', 'pinned')
