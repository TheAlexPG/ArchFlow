"""add edge shape label_size via_object_ids

Revision ID: 5c4164b64c8a
Revises: 32be253b4921
Create Date: 2026-04-16 11:12:02.199733

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '5c4164b64c8a'
down_revision: Union[str, Sequence[str], None] = '32be253b4921'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type first
    edge_shape = postgresql.ENUM('CURVED', 'STRAIGHT', 'STEP', 'SMOOTHSTEP', name='edge_shape')
    edge_shape.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'connections',
        sa.Column('shape', sa.Enum('CURVED', 'STRAIGHT', 'STEP', 'SMOOTHSTEP', name='edge_shape', create_type=False), nullable=False, server_default='CURVED'),
    )
    op.add_column(
        'connections',
        sa.Column('label_size', sa.Float(), nullable=False, server_default='11.0'),
    )
    op.add_column(
        'connections',
        sa.Column('via_object_ids', postgresql.ARRAY(sa.String()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('connections', 'via_object_ids')
    op.drop_column('connections', 'label_size')
    op.drop_column('connections', 'shape')
    op.execute('DROP TYPE IF EXISTS edge_shape')
