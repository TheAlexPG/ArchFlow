"""add workspace to activity_target_type enum

Revision ID: c0dbe5b00011
Revises: c0dbe5b00010
"""
from collections.abc import Sequence

from alembic import op


revision: str = "c0dbe5b00011"
down_revision: str | Sequence[str] | None = "c0dbe5b00010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE activity_target_type ADD VALUE IF NOT EXISTS 'WORKSPACE'")


def downgrade() -> None:
    # Postgres does not support removing enum values without recreating the type.
    # Mark as no-op — the value is harmless to leave in place.
    pass
