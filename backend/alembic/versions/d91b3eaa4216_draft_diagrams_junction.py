"""draft_diagrams junction

Revision ID: d91b3eaa4216
Revises: e4a7f219b8d0
Create Date: 2026-04-20 11:34:04.765211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd91b3eaa4216'
down_revision: Union[str, Sequence[str], None] = 'e4a7f219b8d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create the new junction table.
    op.create_table(
        'draft_diagrams',
        sa.Column('draft_id', sa.UUID(), nullable=False),
        sa.Column('source_diagram_id', sa.UUID(), nullable=False),
        sa.Column('forked_diagram_id', sa.UUID(), nullable=False),
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['draft_id'], ['drafts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['forked_diagram_id'], ['diagrams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_diagram_id'], ['diagrams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('draft_id', 'source_diagram_id', name='uq_draft_source_diagram'),
    )

    # 2. Data-migrate: for every drafts row that had both source_diagram_id and
    #    forked_diagram_id set, create a matching draft_diagrams row.
    op.execute(
        """
        INSERT INTO draft_diagrams (id, draft_id, source_diagram_id, forked_diagram_id,
                                    created_at, updated_at)
        SELECT gen_random_uuid(), id, source_diagram_id, forked_diagram_id,
               now(), now()
        FROM drafts
        WHERE source_diagram_id IS NOT NULL
          AND forked_diagram_id IS NOT NULL
        """
    )

    # 3. Drop indexes that referred to the old columns (autogenerate detected
    #    them as "removed" because the model no longer defines them; keeping
    #    them in the DB would be harmless but we clean up for consistency).
    op.drop_index('ix_connections_draft_id', table_name='connections')
    op.drop_index('ix_diagrams_draft_id', table_name='diagrams')
    op.drop_index('ix_model_objects_draft_id', table_name='model_objects')

    # 4. Drop the now-redundant columns from drafts.
    op.drop_constraint('fk_drafts_source_diagram', 'drafts', type_='foreignkey')
    op.drop_constraint('fk_drafts_forked_diagram', 'drafts', type_='foreignkey')
    op.drop_column('drafts', 'source_diagram_id')
    op.drop_column('drafts', 'forked_diagram_id')

    # 5. Re-create the indexes (still useful for draft-scoped queries).
    op.create_index('ix_connections_draft_id', 'connections', ['draft_id'])
    op.create_index('ix_diagrams_draft_id', 'diagrams', ['draft_id'])
    op.create_index('ix_model_objects_draft_id', 'model_objects', ['draft_id'])


def downgrade() -> None:
    """Reverse the migration.

    NOTE: If a draft had more than one DraftDiagram row, only the first one
    (ordered by created_at) is migrated back to the singleton columns. The
    remaining DraftDiagram rows are lost. This is acceptable and documented.
    """
    # 1. Restore the two columns on drafts.
    op.add_column('drafts', sa.Column('source_diagram_id', sa.UUID(), nullable=True))
    op.add_column('drafts', sa.Column('forked_diagram_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_drafts_forked_diagram', 'drafts', 'diagrams',
                          ['forked_diagram_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_drafts_source_diagram', 'drafts', 'diagrams',
                          ['source_diagram_id'], ['id'], ondelete='SET NULL')

    # 2. Data-migrate back: copy the first DraftDiagram per draft.
    op.execute(
        """
        UPDATE drafts d
        SET source_diagram_id = dd.source_diagram_id,
            forked_diagram_id = dd.forked_diagram_id
        FROM (
            SELECT DISTINCT ON (draft_id)
                   draft_id, source_diagram_id, forked_diagram_id
            FROM draft_diagrams
            ORDER BY draft_id, created_at
        ) dd
        WHERE d.id = dd.draft_id
        """
    )

    # 3. Drop the junction table.
    op.drop_table('draft_diagrams')

    # 4. Restore the indexes that the upgrade step removed then re-created
    #    (they still exist after upgrade, nothing to recreate).
