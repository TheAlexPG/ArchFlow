"""object_technology_ids: replace model_objects.technology (VARCHAR[]) with
technology_ids (UUID[])

Revision ID: c0dbe5b00003
Revises: c0dbe5b00002
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c0dbe5b00003"
down_revision: str | Sequence[str] | None = "c0dbe5b00002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ArchFlow is pre-release — existing free-text technology values are
    # discarded rather than heuristically mapped to catalog slugs. Drop
    # and add fresh.
    op.drop_column("model_objects", "technology")
    op.add_column(
        "model_objects",
        sa.Column(
            "technology_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("model_objects", "technology_ids")
    op.add_column(
        "model_objects",
        sa.Column("technology", postgresql.ARRAY(sa.String()), nullable=True),
    )
