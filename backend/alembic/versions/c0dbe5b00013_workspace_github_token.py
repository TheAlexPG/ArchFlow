"""Add encrypted GitHub token to workspaces.

Revision ID: c0dbe5b00013
Revises: c0dbe5b00012
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0dbe5b00013"
down_revision: str | Sequence[str] | None = "c0dbe5b00012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Same column type as workspace_agent_setting.value_encrypted (LargeBinary)
    # so the existing secret_service Fernet helper can reuse the codepath.
    op.add_column(
        "workspaces",
        sa.Column("github_token_encrypted", sa.LargeBinary(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "github_token_encrypted")
