"""add undo entries and user undo settings

Revision ID: 0246c9846364
Revises: c0dbe5b00006
Create Date: 2026-05-04 15:46:57.071782

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0246c9846364"
down_revision = "c0dbe5b00006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    target_type = postgresql.ENUM(
        "object", "connection", "diagram_object", "edge_property", "comment",
        name="undo_target_type",
    )
    target_type.create(op.get_bind(), checkfirst=True)

    action = postgresql.ENUM(
        "create", "update", "delete",
        name="undo_action",
    )
    action.create(op.get_bind(), checkfirst=True)

    state = postgresql.ENUM(
        "active", "undone", "skipped",
        name="undo_state",
    )
    state.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "undo_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("diagram_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("diagrams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("drafts.id", ondelete="CASCADE"), nullable=True),
        sa.Column("seq", sa.BigInteger, nullable=False),
        sa.Column("target_type",
                  postgresql.ENUM(name="undo_target_type", create_type=False),
                  nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action",
                  postgresql.ENUM(name="undo_action", create_type=False),
                  nullable=False),
        sa.Column("forward_summary", sa.Text, nullable=False),
        sa.Column("inverse_payload", postgresql.JSONB, nullable=False),
        sa.Column("redo_payload", postgresql.JSONB, nullable=True),
        sa.Column("after_state", postgresql.JSONB, nullable=True),
        sa.Column("coalesce_key", sa.Text, nullable=False),
        sa.Column("state",
                  postgresql.ENUM(name="undo_state", create_type=False),
                  nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(
        "ix_undo_entries_stack",
        "undo_entries",
        ["user_id", "diagram_id", "draft_id", sa.text("seq DESC")],
    )
    op.create_index(
        "ix_undo_entries_coalesce",
        "undo_entries",
        ["user_id", "diagram_id", "draft_id", "coalesce_key",
         sa.text("updated_at DESC")],
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "ix_undo_entries_sweep",
        "undo_entries",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_undo_entries_target",
        "undo_entries",
        ["target_id", "target_type"],
    )
    op.create_index(
        "ix_undo_entries_diagram_id",
        "undo_entries",
        ["diagram_id"],
    )
    op.create_index(
        "ix_undo_entries_draft_id",
        "undo_entries",
        ["draft_id"],
    )

    op.add_column(
        "users",
        sa.Column("undo_settings", postgresql.JSONB,
                  nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("users", "undo_settings")
    op.drop_index("ix_undo_entries_draft_id", table_name="undo_entries")
    op.drop_index("ix_undo_entries_diagram_id", table_name="undo_entries")
    op.drop_index("ix_undo_entries_target", table_name="undo_entries")
    op.drop_index("ix_undo_entries_sweep", table_name="undo_entries")
    op.drop_index("ix_undo_entries_coalesce", table_name="undo_entries")
    op.drop_index("ix_undo_entries_stack", table_name="undo_entries")
    op.drop_table("undo_entries")
    postgresql.ENUM(name="undo_state").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="undo_action").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="undo_target_type").drop(op.get_bind(), checkfirst=True)
