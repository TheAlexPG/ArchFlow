"""activity_target_technology: add 'technology' to activity_target_type enum

Revision ID: c0dbe5b00002
Revises: c0dbe5b00001
"""
from collections.abc import Sequence

from alembic import op

revision: str = "c0dbe5b00002"
down_revision: str | Sequence[str] | None = "c0dbe5b00001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE is the only ALTER TYPE operation that cannot run inside
    # a transaction in older Postgres versions — autocommit_block makes it
    # safe regardless of server version.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE activity_target_type ADD VALUE IF NOT EXISTS 'technology'"
        )


def downgrade() -> None:
    # Postgres does not support removing a value from an enum without
    # rebuilding the type. Downgrade is a no-op; the unused value is harmless.
    pass
