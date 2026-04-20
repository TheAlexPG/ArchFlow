"""versions table + drafts.base_version_id

Revision ID: 2964f358c796
Revises: 7a9f7916de28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '2964f358c796'
down_revision: Union[str, Sequence[str], None] = '7a9f7916de28'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE version_source AS ENUM "
        "('apply', 'manual', 'scheduled', 'revert')"
    )
    source_enum = postgresql.ENUM(
        'apply', 'manual', 'scheduled', 'revert',
        name='version_source',
        create_type=False,
    )

    op.create_table(
        'versions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('label', sa.String(length=64), nullable=False),
        sa.Column('source', source_enum, nullable=False),
        sa.Column('draft_id', sa.UUID(), nullable=True),
        sa.Column('snapshot_data', postgresql.JSONB(), nullable=False),
        sa.Column('created_by_user_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_versions_workspace_id', 'versions', ['workspace_id'])
    op.create_index(
        'ix_versions_workspace_created',
        'versions', ['workspace_id', 'created_at'],
    )

    # Track which version a draft was forked off of. Set at draft-create
    # time (or null for legacy drafts that predate this migration).
    op.add_column(
        'drafts',
        sa.Column('base_version_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_drafts_base_version_id',
        'drafts', 'versions',
        ['base_version_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_drafts_base_version_id', 'drafts', type_='foreignkey')
    op.drop_column('drafts', 'base_version_id')
    op.drop_index('ix_versions_workspace_created', table_name='versions')
    op.drop_index('ix_versions_workspace_id', table_name='versions')
    op.drop_table('versions')
    op.execute("DROP TYPE IF EXISTS version_source")
