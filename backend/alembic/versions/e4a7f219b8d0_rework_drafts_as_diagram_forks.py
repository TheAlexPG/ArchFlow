"""rework drafts as diagram forks

Revision ID: e4a7f219b8d0
Revises: c7e4a8d12f91
Create Date: 2026-04-16 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e4a7f219b8d0'
down_revision: Union[str, Sequence[str], None] = 'c7e4a8d12f91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop legacy per-field draft items — replaced by full-diagram fork model.
    op.drop_index('ix_draft_items_draft_id', table_name='draft_items')
    op.drop_table('draft_items')

    # Drafts now point at the source diagram they were forked from and the
    # clone ("forked") diagram where the user edits in isolation.
    op.add_column('drafts', sa.Column('source_diagram_id', sa.UUID(), nullable=True))
    op.add_column('drafts', sa.Column('forked_diagram_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_drafts_source_diagram', 'drafts', 'diagrams',
                          ['source_diagram_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_drafts_forked_diagram', 'drafts', 'diagrams',
                          ['forked_diagram_id'], ['id'], ondelete='SET NULL')

    # Objects/connections/diagrams can now be draft-scoped. Default queries
    # filter draft_id IS NULL so the live model stays clean.
    op.add_column('model_objects', sa.Column('draft_id', sa.UUID(), nullable=True))
    op.add_column('model_objects', sa.Column('source_object_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_model_objects_draft', 'model_objects', 'drafts',
                          ['draft_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_model_objects_source', 'model_objects', 'model_objects',
                          ['source_object_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_model_objects_draft_id', 'model_objects', ['draft_id'])

    op.add_column('connections', sa.Column('draft_id', sa.UUID(), nullable=True))
    op.add_column('connections', sa.Column('source_connection_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_connections_draft', 'connections', 'drafts',
                          ['draft_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_connections_source', 'connections', 'connections',
                          ['source_connection_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_connections_draft_id', 'connections', ['draft_id'])

    op.add_column('diagrams', sa.Column('draft_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_diagrams_draft', 'diagrams', 'drafts',
                          ['draft_id'], ['id'], ondelete='CASCADE')
    op.create_index('ix_diagrams_draft_id', 'diagrams', ['draft_id'])


def downgrade() -> None:
    op.drop_index('ix_diagrams_draft_id', table_name='diagrams')
    op.drop_constraint('fk_diagrams_draft', 'diagrams', type_='foreignkey')
    op.drop_column('diagrams', 'draft_id')

    op.drop_index('ix_connections_draft_id', table_name='connections')
    op.drop_constraint('fk_connections_source', 'connections', type_='foreignkey')
    op.drop_constraint('fk_connections_draft', 'connections', type_='foreignkey')
    op.drop_column('connections', 'source_connection_id')
    op.drop_column('connections', 'draft_id')

    op.drop_index('ix_model_objects_draft_id', table_name='model_objects')
    op.drop_constraint('fk_model_objects_source', 'model_objects', type_='foreignkey')
    op.drop_constraint('fk_model_objects_draft', 'model_objects', type_='foreignkey')
    op.drop_column('model_objects', 'source_object_id')
    op.drop_column('model_objects', 'draft_id')

    op.drop_constraint('fk_drafts_forked_diagram', 'drafts', type_='foreignkey')
    op.drop_constraint('fk_drafts_source_diagram', 'drafts', type_='foreignkey')
    op.drop_column('drafts', 'forked_diagram_id')
    op.drop_column('drafts', 'source_diagram_id')

    op.create_table(
        'draft_items',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('draft_id', sa.UUID(), nullable=False),
        sa.Column('target_type', sa.String(32), nullable=False, server_default='object'),
        sa.Column('target_id', sa.UUID(), nullable=True),
        sa.Column('baseline', sa.JSON(), nullable=True),
        sa.Column('proposed_state', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_draft_items_draft_id', 'draft_items', ['draft_id'])
