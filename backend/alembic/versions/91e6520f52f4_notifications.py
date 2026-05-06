"""notifications

Revision ID: 91e6520f52f4
Revises: 2964f358c796
Create Date: 2026-04-21 00:58:05.430918

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '91e6520f52f4'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Mirrors ``app.models.notification.Notification`` (UUIDMixin + TimestampMixin
    + per-user notification fields). The original revision shipped empty,
    which only worked when the schema was bootstrapped via
    ``Base.metadata.create_all`` outside Alembic. Restoring the real CREATE
    so a clean ``alembic upgrade head`` builds a working schema.
    """
    op.create_table(
        "notifications",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("target_url", sa.String(512), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_notifications_user_id", "notifications", ["user_id"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
