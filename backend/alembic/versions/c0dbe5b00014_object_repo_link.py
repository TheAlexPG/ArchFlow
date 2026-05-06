"""Add repo_url + repo_branch to model_objects.

Repo links live only on Container (app/store) and System object types.
The service layer enforces that constraint; the DB stores nullable text
so the existing live + draft fork rows don't need a backfill.

Revision ID: c0dbe5b00014
Revises: c0dbe5b00013
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0dbe5b00014"
down_revision: str | Sequence[str] | None = "c0dbe5b00013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_objects",
        sa.Column("repo_url", sa.Text(), nullable=True),
    )
    op.add_column(
        "model_objects",
        sa.Column("repo_branch", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_objects", "repo_branch")
    op.drop_column("model_objects", "repo_url")
