"""Allow diagram_access to grant to a user directly, not only to a team.

Either team_id or user_id must be set (CHECK). Unique constraints updated to
separate the two grantee kinds so granting the same team and the same user
independently is fine.

Revision ID: 648de0788239
Revises: cc179e2f5273
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '648de0788239'
down_revision: Union[str, Sequence[str], None] = 'cc179e2f5273'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'diagram_access',
        sa.Column('user_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_diagram_access_user_id',
        'diagram_access', 'users',
        ['user_id'], ['id'],
        ondelete='CASCADE',
    )
    op.create_index(
        'ix_diagram_access_user_id', 'diagram_access', ['user_id']
    )
    # team_id is now optional — grants can target a user or a team.
    op.alter_column('diagram_access', 'team_id', nullable=True)

    # Replace the old unique(diagram_id, team_id) with two narrower uniques,
    # so the same diagram can have both team and user grants without the
    # original constraint's NULL behaviour biting us.
    op.drop_constraint(
        'uq_team_per_diagram_access', 'diagram_access', type_='unique'
    )
    # Postgres treats each NULL as distinct, so a partial unique is cleaner:
    op.execute(
        "CREATE UNIQUE INDEX uq_team_per_diagram_access "
        "ON diagram_access(diagram_id, team_id) WHERE team_id IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_user_per_diagram_access "
        "ON diagram_access(diagram_id, user_id) WHERE user_id IS NOT NULL"
    )
    # Enforce exactly-one-grantee. Postgres CHECK — either team_id xor user_id.
    op.execute(
        "ALTER TABLE diagram_access ADD CONSTRAINT diagram_access_grantee_ck "
        "CHECK ((team_id IS NOT NULL)::int + (user_id IS NOT NULL)::int = 1)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE diagram_access DROP CONSTRAINT IF EXISTS diagram_access_grantee_ck"
    )
    op.execute("DROP INDEX IF EXISTS uq_user_per_diagram_access")
    op.execute("DROP INDEX IF EXISTS uq_team_per_diagram_access")
    op.create_unique_constraint(
        'uq_team_per_diagram_access', 'diagram_access', ['diagram_id', 'team_id']
    )
    op.alter_column('diagram_access', 'team_id', nullable=False)
    op.drop_index('ix_diagram_access_user_id', table_name='diagram_access')
    op.drop_constraint('fk_diagram_access_user_id', 'diagram_access', type_='foreignkey')
    op.drop_column('diagram_access', 'user_id')
