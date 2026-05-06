"""create message_role enum and convert agent_chat_message.role

Revision ID: c0dbe5b00012
Revises: c0dbe5b00011
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0dbe5b00012"
down_revision: str | Sequence[str] | None = "c0dbe5b00011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ENUM_VALUES = ("USER", "ASSISTANT", "TOOL", "SYSTEM_SUMMARY")


def upgrade() -> None:
    # Create the missing ENUM type that the ORM model declares.
    message_role = sa.Enum(*_ENUM_VALUES, name="message_role")
    message_role.create(op.get_bind(), checkfirst=True)

    # Convert role column from VARCHAR(32) to message_role.
    op.execute(
        "ALTER TABLE agent_chat_message "
        "ALTER COLUMN role TYPE message_role "
        "USING role::message_role"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE agent_chat_message "
        "ALTER COLUMN role TYPE varchar(32) "
        "USING role::text"
    )
    sa.Enum(name="message_role").drop(op.get_bind(), checkfirst=True)
