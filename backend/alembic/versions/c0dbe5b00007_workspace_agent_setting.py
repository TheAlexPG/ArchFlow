"""workspace_agent_setting: store per-workspace agent settings with optional encryption

Revision ID: c0dbe5b00007
Revises: c0dbe5b00006
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00007"
down_revision: str | Sequence[str] | None = "c0dbe5b00006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_agent_setting",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=True),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value_plain", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column(
            "is_secret",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["users.id"], ondelete="SET NULL"
        ),
    )

    # Index for efficient resolution queries: (workspace_id, agent_id)
    op.create_index(
        "ix_workspace_agent_setting_workspace_agent",
        "workspace_agent_setting",
        ["workspace_id", "agent_id"],
    )

    # UNIQUE(workspace_id, agent_id, key) with NULL-safe semantics.
    # Postgres treats NULLs as distinct in regular unique constraints, so a
    # single UNIQUE constraint would allow duplicate (workspace_id, NULL, key)
    # rows. We use two partial indexes instead — matching the convention
    # established in this codebase (see uq_technologies_builtin_slug):
    #   - one index for rows where agent_id IS NOT NULL
    #   - one index for rows where agent_id IS NULL (global workspace defaults)
    op.create_index(
        "uq_workspace_agent_setting_with_agent",
        "workspace_agent_setting",
        ["workspace_id", "agent_id", "key"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NOT NULL"),
    )
    op.create_index(
        "uq_workspace_agent_setting_global",
        "workspace_agent_setting",
        ["workspace_id", "key"],
        unique=True,
        postgresql_where=sa.text("agent_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_workspace_agent_setting_global",
        table_name="workspace_agent_setting",
    )
    op.drop_index(
        "uq_workspace_agent_setting_with_agent",
        table_name="workspace_agent_setting",
    )
    op.drop_index(
        "ix_workspace_agent_setting_workspace_agent",
        table_name="workspace_agent_setting",
    )
    op.drop_table("workspace_agent_setting")
