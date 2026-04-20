"""organizations + workspaces + workspace_members; backfill personal workspace per user

Revision ID: 9e93425c2400
Revises: b3c3fc1f069d
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '9e93425c2400'
down_revision: Union[str, Sequence[str], None] = 'b3c3fc1f069d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE workspace_role AS ENUM "
        "('owner', 'admin', 'editor', 'reviewer', 'viewer')"
    )
    role_enum = postgresql.ENUM(
        'owner', 'admin', 'editor', 'reviewer', 'viewer',
        name='workspace_role',
        create_type=False,
    )

    op.create_table(
        'organizations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_organizations_slug', 'organizations', ['slug'], unique=True)

    op.create_table(
        'workspaces',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('slug', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('org_id', 'slug', name='uq_workspace_slug_per_org'),
    )
    op.create_index('ix_workspaces_org_id', 'workspaces', ['org_id'])

    op.create_table(
        'workspace_members',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('workspace_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role', role_enum, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'user_id', name='uq_member_per_workspace'),
    )
    op.create_index('ix_workspace_members_workspace_id', 'workspace_members', ['workspace_id'])
    op.create_index('ix_workspace_members_user_id', 'workspace_members', ['user_id'])

    # Backfill: give every existing user a "personal" org + workspace with
    # owner membership. Uses gen_random_uuid() from pgcrypto (available by
    # default on modern Postgres) and derives slugs from the user id so they
    # stay unique without name collision.
    op.execute(
        """
        INSERT INTO organizations (id, name, slug)
        SELECT gen_random_uuid(), u.name || '''s personal org', 'personal-' || u.id
        FROM users u
        """
    )
    op.execute(
        """
        INSERT INTO workspaces (id, org_id, name, slug)
        SELECT gen_random_uuid(), o.id, 'Personal', 'personal'
        FROM organizations o
        WHERE o.slug LIKE 'personal-%'
        """
    )
    op.execute(
        """
        INSERT INTO workspace_members (id, workspace_id, user_id, role)
        SELECT gen_random_uuid(), w.id, u.id, 'owner'
        FROM users u
        JOIN organizations o ON o.slug = 'personal-' || u.id
        JOIN workspaces w ON w.org_id = o.id
        """
    )


def downgrade() -> None:
    op.drop_index('ix_workspace_members_user_id', table_name='workspace_members')
    op.drop_index('ix_workspace_members_workspace_id', table_name='workspace_members')
    op.drop_table('workspace_members')
    op.drop_index('ix_workspaces_org_id', table_name='workspaces')
    op.drop_table('workspaces')
    op.drop_index('ix_organizations_slug', table_name='organizations')
    op.drop_table('organizations')
    op.execute("DROP TYPE IF EXISTS workspace_role")
