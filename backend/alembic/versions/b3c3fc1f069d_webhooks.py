"""webhooks

Revision ID: b3c3fc1f069d
Revises: 5a9694319386
Create Date: 2026-04-20 19:52:19.929940

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c3fc1f069d'
down_revision: Union[str, Sequence[str], None] = '5a9694319386'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'webhooks',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column(
            'events',
            sa.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column('secret', sa.String(length=128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('failure_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_delivery_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_webhooks_user_id', 'webhooks', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_webhooks_user_id', table_name='webhooks')
    op.drop_table('webhooks')
