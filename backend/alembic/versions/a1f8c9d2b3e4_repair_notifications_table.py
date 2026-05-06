"""repair notifications table (idempotent)

Revision ID: a1f8c9d2b3e4
Revises: f359350166f3
Create Date: 2026-05-06 12:00:00.000000

The original ``91e6520f52f4_notifications`` revision shipped with empty
``upgrade()``/``downgrade()`` bodies. Existing prod deploys ran past it
without creating the ``notifications`` table — but Alembic still recorded
the revision as applied, so the corrected upgrade() never reruns there.

This migration creates the table idempotently (``CREATE TABLE IF NOT
EXISTS``) so anyone upgrading from a buggy state finally gets it, while
clean deploys (where 91e6520f52f4's fixed upgrade did the work already)
treat this as a no-op.

Mirrors ``app.models.notification.Notification`` exactly.
"""
from collections.abc import Sequence

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a1f8c9d2b3e4"
down_revision: str | Sequence[str] | None = "f359350166f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id            UUID PRIMARY KEY,
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind          VARCHAR(64) NOT NULL,
            title         VARCHAR(255) NOT NULL,
            body          TEXT,
            target_url    VARCHAR(512),
            read_at       TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_notifications_user_id "
        "ON notifications (user_id);"
    )


def downgrade() -> None:
    # Intentionally a no-op: dropping the table here would also strip it
    # from clean deploys where 91e6520f52f4 created it. Use the original
    # revision's downgrade if you need to remove it.
    pass
