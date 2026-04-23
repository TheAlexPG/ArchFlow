"""Change default shape for connections from CURVED to SMOOTHSTEP.

Existing rows keep their current shape value; this migration only changes the
column server-default so new connections created after this migration default
to smoothstep instead of curved.

Revision ID: eb9e2003d7b9
Revises: a7b8c9d0e1f2
Create Date: 2026-04-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: I001

from alembic import op

revision: str = "eb9e2003d7b9"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "connections",
        "shape",
        existing_type=sa.Enum(
            "CURVED", "STRAIGHT", "STEP", "SMOOTHSTEP", name="edge_shape"
        ),
        server_default="SMOOTHSTEP",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "connections",
        "shape",
        existing_type=sa.Enum(
            "CURVED", "STRAIGHT", "STEP", "SMOOTHSTEP", name="edge_shape"
        ),
        server_default="CURVED",
        existing_nullable=False,
    )
