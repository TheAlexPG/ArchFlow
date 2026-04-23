"""Add undirected value to connection_direction enum.

Revision ID: f1a2b3c4d5e6
Revises: d7a3c8b91e02
Create Date: 2026-04-23 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "d7a3c8b91e02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Postgres does not support removing enum values (only adding them), so the
    # downgrade is intentionally a no-op.  A full drop/recreate of the type
    # would be required to remove the value — see downgrade() note below.
    op.execute("ALTER TYPE connection_direction ADD VALUE IF NOT EXISTS 'undirected'")


def downgrade() -> None:
    # Postgres cannot remove a value from an existing enum type without
    # dropping and recreating it, which requires migrating all data first.
    # This is intentionally left as a no-op; remove the enum value manually
    # if you truly need to roll back (requires recreating the type and
    # updating all affected rows).
    pass
