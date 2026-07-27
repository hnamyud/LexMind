"""Create the pre-cutover application schema.

This revision is a baseline for production databases previously managed by
Prisma.  Production must be stamped at this revision before upgrading to head.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260727_prisma_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("password", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), server_default=sa.text("'USER'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        sa.UniqueConstraint("email", name="users_email_key"),
        sa.UniqueConstraint("refresh_token", name="users_refresh_token_key"),
    )
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="conversations_user_id_fkey", ondelete="CASCADE", onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="conversations_pkey"),
    )
    op.create_index("conversations_user_id_idx", "conversations", ["user_id"])
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("thought", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], name="messages_conversation_id_fkey", ondelete="CASCADE", onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="messages_pkey"),
    )
    op.create_index("idx_messages_history", "messages", ["conversation_id", "created_at"])
    op.create_table(
        "feedbacks",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_like", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="feedbacks_message_id_fkey", ondelete="CASCADE", onupdate="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="feedbacks_user_id_fkey", ondelete="CASCADE", onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="feedbacks_pkey"),
        sa.UniqueConstraint("message_id", "user_id", name="feedbacks_message_id_user_id_key"),
    )
    op.create_table(
        "ai_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("time_to_first_token", sa.Integer(), nullable=True),
        sa.Column("total_time", sa.Integer(), nullable=True),
        sa.Column("graph_query_time", sa.Integer(), nullable=True),
        sa.Column("web_search_time", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("thinking_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_calls", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column("tool_call_details", postgresql.JSONB(), nullable=True),
        sa.Column("cost", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("cache_check_time", sa.Integer(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="ai_metrics_message_id_fkey", ondelete="CASCADE", onupdate="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="ai_metrics_pkey"),
        sa.UniqueConstraint("message_id", name="ai_metrics_message_id_key"),
    )
    op.create_index("ai_metrics_message_id_idx", "ai_metrics", ["message_id"])
    op.create_index("ai_metrics_created_at_idx", "ai_metrics", ["created_at"])
    op.create_index("ai_metrics_model_idx", "ai_metrics", ["model"])
    op.create_index("ai_metrics_total_time_idx", "ai_metrics", ["total_time"])


def downgrade() -> None:
    op.drop_index("ai_metrics_total_time_idx", table_name="ai_metrics")
    op.drop_index("ai_metrics_model_idx", table_name="ai_metrics")
    op.drop_index("ai_metrics_created_at_idx", table_name="ai_metrics")
    op.drop_index("ai_metrics_message_id_idx", table_name="ai_metrics")
    op.drop_table("ai_metrics")
    op.drop_table("feedbacks")
    op.drop_index("idx_messages_history", table_name="messages")
    op.drop_table("messages")
    op.drop_index("conversations_user_id_idx", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("users")
