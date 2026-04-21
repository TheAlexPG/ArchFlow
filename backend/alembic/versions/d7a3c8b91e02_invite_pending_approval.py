"""Pending-approval invites: add declined_at column.

Flow change: invites are no longer auto-accepted when the email already
has an account. The invitee must explicitly accept (or decline) via
/api/v1/me/invites/{id}/accept|decline. `declined_at` lets us keep
history and stop the invite from showing up as pending.

Revision ID: d7a3c8b91e02
Revises: 91e6520f52f4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3c8b91e02"
down_revision: Union[str, Sequence[str], None] = "91e6520f52f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspace_invites",
        sa.Column("declined_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspace_invites", "declined_at")
