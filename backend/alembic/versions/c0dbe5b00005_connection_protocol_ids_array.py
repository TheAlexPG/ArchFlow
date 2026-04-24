"""connection_protocol_ids_array: widen connections.protocol_id → protocol_ids

Revision ID: c0dbe5b00005
Revises: c0dbe5b00004

Rationale: connections regularly carry more than one protocol (e.g. HTTP
over TLS, gRPC over HTTP/2, or TCP + TLS) and the single-slot column
forced users to pick one arbitrarily. Match `model_objects.technology_ids`
so edges and nodes use the same vocabulary.

Pre-release, so existing values are discarded rather than migrated.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00005"
down_revision: str | Sequence[str] | None = "c0dbe5b00004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_connections_protocol_id", table_name="connections")
    op.drop_column("connections", "protocol_id")
    op.add_column(
        "connections",
        sa.Column(
            "protocol_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("connections", "protocol_ids")
    op.add_column(
        "connections",
        sa.Column("protocol_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_connections_protocol_id", "connections", ["protocol_id"]
    )
