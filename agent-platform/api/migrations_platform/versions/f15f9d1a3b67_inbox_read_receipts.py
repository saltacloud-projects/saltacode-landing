"""Track explicit inbound-message visibility per operator without invented history.

Revision ID: f15f9d1a3b67
Revises: f14e8c0f2a56
"""

import sqlalchemy as sa
from alembic import op

revision = "f15f9d1a3b67"
down_revision = "f14e8c0f2a56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbox_read_receipts",
        sa.Column("admin_user_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "read_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("admin_user_id", "message_id"),
        sa.ForeignKeyConstraint(
            ["admin_user_id"], ["admin_users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["chat_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["chat_conversations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_inbox_read_receipt_admin_conversation",
        "inbox_read_receipts",
        ["admin_user_id", "conversation_id"],
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT EXISTS (SELECT 1 FROM inbox_read_receipts)"))
        .scalar()
    ):
        raise RuntimeError("Cannot discard persisted operator read receipts")
    op.drop_table("inbox_read_receipts")
