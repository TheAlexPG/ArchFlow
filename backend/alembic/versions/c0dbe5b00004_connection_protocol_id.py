"""connection_protocol_id: replace connections.protocol (VARCHAR) with
protocol_id (UUID) referencing the technology catalog.

Revision ID: c0dbe5b00004
Revises: c0dbe5b00003
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00004"
down_revision: str | Sequence[str] | None = "c0dbe5b00003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Pre-release: existing free-text protocol values are discarded.
    op.drop_column("connections", "protocol")
    op.add_column(
        "connections",
        sa.Column("protocol_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_connections_protocol_id", "connections", ["protocol_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_connections_protocol_id", table_name="connections")
    op.drop_column("connections", "protocol_id")
    op.add_column(
        "connections",
        sa.Column("protocol", sa.String(100), nullable=True),
    )
