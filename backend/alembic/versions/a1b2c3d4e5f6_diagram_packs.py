"""diagram_packs

Revision ID: a1b2c3d4e5f6
Revises: 2964f358c796
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '2964f358c796'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'diagram_packs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_diagram_packs_workspace_id', 'diagram_packs', ['workspace_id'])

    op.add_column('diagrams', sa.Column('pack_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_diagrams_pack_id',
        'diagrams', 'diagram_packs',
        ['pack_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_diagrams_pack_id', 'diagrams', ['pack_id'])


def downgrade() -> None:
    op.drop_index('ix_diagrams_pack_id', table_name='diagrams')
    op.drop_constraint('fk_diagrams_pack_id', 'diagrams', type_='foreignkey')
    op.drop_column('diagrams', 'pack_id')

    op.drop_index('ix_diagram_packs_workspace_id', table_name='diagram_packs')
    op.drop_table('diagram_packs')
