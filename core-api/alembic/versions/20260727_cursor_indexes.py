"""Add keyset-pagination indexes after the Prisma baseline."""

from alembic import op


revision = "20260727_cursor_indexes"
down_revision = "20260727_prisma_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_user_cursor "
        "ON conversations (user_id, is_deleted, updated_at DESC, id DESC)"
    )
    op.execute("DROP INDEX IF EXISTS idx_messages_history")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_history_cursor "
        "ON messages (conversation_id, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_messages_history_cursor")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_history "
        "ON messages (conversation_id, created_at)"
    )
    op.execute("DROP INDEX IF EXISTS idx_conversations_user_cursor")
