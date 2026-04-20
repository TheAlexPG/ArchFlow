"""teams + team_members + diagram_access + workspace_invites + users.auth_provider

Revision ID: cc179e2f5273
Revises: e5d9e94e25ff
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'cc179e2f5273'
down_revision: Union[str, Sequence[str], None] = 'e5d9e94e25ff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE access_level AS ENUM ('read', 'write', 'admin')"
    )
    access_enum = postgresql.ENUM(
        'read', 'write', 'admin',
        name='access_level',
        create_type=False,
    )

    op.create_table(
        'teams',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'slug', name='uq_team_slug_per_workspace'),
    )
    op.create_index('ix_teams_workspace_id', 'teams', ['workspace_id'])

    op.create_table(
        'team_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('team_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('team_id', 'user_id', name='uq_user_per_team'),
    )
    op.create_index('ix_team_members_team_id', 'team_members', ['team_id'])
    op.create_index('ix_team_members_user_id', 'team_members', ['user_id'])

    op.create_table(
        'diagram_access',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('diagram_id', sa.UUID(), nullable=False),
        sa.Column('team_id', sa.UUID(), nullable=False),
        sa.Column('access_level', access_enum, nullable=False, server_default='read'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['diagram_id'], ['diagrams.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('diagram_id', 'team_id', name='uq_team_per_diagram_access'),
    )
    op.create_index('ix_diagram_access_diagram_id', 'diagram_access', ['diagram_id'])
    op.create_index('ix_diagram_access_team_id', 'diagram_access', ['team_id'])

    op.create_table(
        'workspace_invites',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('role', postgresql.ENUM(name='workspace_role', create_type=False), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('invited_by_user_id', sa.UUID(), nullable=True),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token', name='uq_invite_token'),
    )
    op.create_index('ix_workspace_invites_workspace_id', 'workspace_invites', ['workspace_id'])
    op.create_index('ix_workspace_invites_email', 'workspace_invites', ['email'])

    # auth_provider on users — for OAuth stub. 'local' for normal login.
    op.add_column(
        'users',
        sa.Column(
            'auth_provider',
            sa.String(length=32),
            nullable=False,
            server_default='local',
        ),
    )


def downgrade() -> None:
    op.drop_column('users', 'auth_provider')
    op.drop_index('ix_workspace_invites_email', table_name='workspace_invites')
    op.drop_index('ix_workspace_invites_workspace_id', table_name='workspace_invites')
    op.drop_table('workspace_invites')
    op.drop_index('ix_diagram_access_team_id', table_name='diagram_access')
    op.drop_index('ix_diagram_access_diagram_id', table_name='diagram_access')
    op.drop_table('diagram_access')
    op.drop_index('ix_team_members_user_id', table_name='team_members')
    op.drop_index('ix_team_members_team_id', table_name='team_members')
    op.drop_table('team_members')
    op.drop_index('ix_teams_workspace_id', table_name='teams')
    op.drop_table('teams')
    op.execute("DROP TYPE IF EXISTS access_level")
