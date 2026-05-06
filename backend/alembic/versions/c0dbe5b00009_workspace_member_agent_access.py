"""workspace_member_agent_access: add agent_access policy columns to workspace_members

Revision ID: c0dbe5b00009
Revises: c0dbe5b00008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00009"
down_revision: str | Sequence[str] | None = "c0dbe5b00008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create the enum type first
    op.execute(
        "CREATE TYPE agent_access_level AS ENUM ('none', 'read_only', 'full')"
    )
    agent_access_enum = postgresql.ENUM(
        "none",
        "read_only",
        "full",
        name="agent_access_level",
        create_type=False,
    )

    # ADD COLUMN agent_access — NOT NULL DEFAULT 'read_only' backfills existing rows
    op.add_column(
        "workspace_members",
        sa.Column(
            "agent_access",
            agent_access_enum,
            nullable=False,
            server_default="read_only",
        ),
    )

    # ADD COLUMN agent_access_updated_at — nullable timestamp
    op.add_column(
        "workspace_members",
        sa.Column(
            "agent_access_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # ADD COLUMN agent_access_updated_by — nullable UUID FK → users.id
    op.add_column(
        "workspace_members",
        sa.Column(
            "agent_access_updated_by",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_workspace_members_agent_access_updated_by",
        "workspace_members",
        "users",
        ["agent_access_updated_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_workspace_members_agent_access_updated_by",
        "workspace_members",
        type_="foreignkey",
    )
    op.drop_column("workspace_members", "agent_access_updated_by")
    op.drop_column("workspace_members", "agent_access_updated_at")
    op.drop_column("workspace_members", "agent_access")
    op.execute("DROP TYPE IF EXISTS agent_access_level")
