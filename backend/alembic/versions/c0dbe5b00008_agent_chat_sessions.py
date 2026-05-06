"""agent_chat_sessions: add agent_chat_session and agent_chat_message tables

Revision ID: c0dbe5b00008
Revises: c0dbe5b00007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00008"
down_revision: str | Sequence[str] | None = "c0dbe5b00007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_chat_session",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context_kind", sa.String(32), nullable=False),
        sa.Column("context_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("context_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column(
            "compaction_stage",
            sa.SmallInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["actor_api_key_id"], ["api_keys.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "(actor_user_id IS NOT NULL)::int + (actor_api_key_id IS NOT NULL)::int = 1",
            name="ck_agent_chat_session_exactly_one_actor",
        ),
    )

    op.create_index(
        "ix_agent_chat_session_ws_actor_last",
        "agent_chat_session",
        [
            "workspace_id",
            "actor_user_id",
            sa.text("last_message_at DESC"),
        ],
    )

    op.create_table(
        "agent_chat_message",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=True),
        sa.Column(
            "content_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("tool_call_id", sa.String(128), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("langfuse_trace_id", sa.String(128), nullable=True),
        sa.Column(
            "is_compacted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_chat_session.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("session_id", "sequence", name="uq_agent_chat_message_session_seq"),
    )

    # Explicit index on (session_id, sequence) — covered by the unique
    # constraint above but kept for clarity and query-planner hints.
    op.create_index(
        "ix_agent_chat_message_session_seq",
        "agent_chat_message",
        ["session_id", "sequence"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_message_session_seq", table_name="agent_chat_message")
    op.drop_table("agent_chat_message")

    op.drop_index("ix_agent_chat_session_ws_actor_last", table_name="agent_chat_session")
    op.drop_table("agent_chat_session")
