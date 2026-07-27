import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    email: Mapped[str] = mapped_column(Text, unique=True)
    password: Mapped[str] = mapped_column(Text)
    full_name: Mapped[str | None] = mapped_column("full_name", Text)
    role: Mapped[str] = mapped_column(Text, server_default=text("'USER'"))
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(), server_default=func.now())
    refresh_token: Mapped[str | None] = mapped_column("refresh_token", Text, unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column("deleted_at", DateTime())


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index("conversations_user_id_idx", "user_id"),
        Index("idx_conversations_user_cursor", "user_id", "is_deleted", text("updated_at DESC"), text("id DESC")),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_id: Mapped[uuid.UUID] = mapped_column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime(), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column("deleted_at", DateTime())
    is_deleted: Mapped[bool] = mapped_column("is_deleted", Boolean, server_default=text("false"))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (Index("idx_messages_history_cursor", "conversation_id", text("created_at DESC"), text("id DESC")),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    conversation_id: Mapped[uuid.UUID] = mapped_column("conversation_id", UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE", onupdate="CASCADE"))
    sender: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    thought: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(), server_default=func.now())
    parent_id: Mapped[uuid.UUID | None] = mapped_column("parent_id", UUID(as_uuid=True))


class Feedback(Base):
    __tablename__ = "feedbacks"
    __table_args__ = (UniqueConstraint("message_id", "user_id", name="feedbacks_message_id_user_id_key"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    message_id: Mapped[uuid.UUID] = mapped_column("message_id", UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE", onupdate="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE", onupdate="CASCADE"))
    is_like: Mapped[bool] = mapped_column("is_like", Boolean)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column("updated_at", DateTime(), server_default=func.now(), onupdate=func.now())


class AIMetrics(Base):
    __tablename__ = "ai_metrics"
    __table_args__ = (
        Index("ai_metrics_message_id_idx", "message_id"),
        Index("ai_metrics_created_at_idx", "created_at"),
        Index("ai_metrics_model_idx", "model"),
        Index("ai_metrics_total_time_idx", "total_time"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    message_id: Mapped[uuid.UUID] = mapped_column("message_id", UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE", onupdate="CASCADE"), unique=True)
    model: Mapped[str] = mapped_column(Text)
    ttft: Mapped[int | None] = mapped_column("time_to_first_token", Integer)
    total_time: Mapped[int | None] = mapped_column("total_time", Integer)
    graph_query_time: Mapped[int | None] = mapped_column("graph_query_time", Integer)
    web_search_time: Mapped[int | None] = mapped_column("web_search_time", Integer)
    input_tokens: Mapped[int | None] = mapped_column("input_tokens", Integer)
    output_tokens: Mapped[int | None] = mapped_column("output_tokens", Integer)
    thinking_tokens: Mapped[int | None] = mapped_column("thinking_tokens", Integer)
    tool_calls: Mapped[int | None] = mapped_column("tool_calls", Integer)
    tool_call_details: Mapped[dict | None] = mapped_column("tool_call_details", JSONB)
    cost: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column("error_type", Text)
    retry_count: Mapped[int | None] = mapped_column("retry_count", Integer)
    cache_hit: Mapped[bool] = mapped_column("cache_hit", Boolean, server_default=text("false"))
    cache_check_time: Mapped[int | None] = mapped_column("cache_check_time", Integer)
    created_at: Mapped[datetime] = mapped_column("created_at", DateTime(), server_default=func.now())
