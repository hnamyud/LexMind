import base64
import json
import math
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import DB
from app.core.responses import ApiError, envelope
from app.core.security import current_user
from app.db.models import Conversation, Feedback, Message
from app.schemas import FeedbackBody, UpdateConversationBody

conversations = APIRouter(prefix="/conversations", tags=["Conversations"])
messages = APIRouter(prefix="/messages", tags=["Messages"])
feedbacks = APIRouter(prefix="/feedbacks", tags=["Feedbacks"])


def _conversation_data(item: Conversation) -> dict:
    return {"id": str(item.id), "title": item.title, "summary": item.summary, "createdAt": item.created_at, "updatedAt": item.updated_at}


def _encode_cursor(timestamp: datetime, record_id: uuid.UUID) -> str:
    payload = json.dumps(
        {"timestamp": timestamp.isoformat(), "id": str(record_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        timestamp = datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp, uuid.UUID(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise ApiError(400, "Cursor không hợp lệ")


async def owned_conversation(session: DB, conversation_id: str, user: dict) -> Conversation:
    try:
        record = await session.scalar(select(Conversation).where(Conversation.id == uuid.UUID(conversation_id), Conversation.is_deleted.is_(False)))
    except ValueError:
        record = None
    if not record:
        raise ApiError(400, f"Conversation: {conversation_id} không tồn tại")
    if str(record.user_id) != user["id"]:
        raise ApiError(401, "Bạn không có quyền truy cập vào cuộc trò chuyện này", "Unauthorized")
    return record


@conversations.get("/")
async def list_conversations(session: DB, current: int = 1, page_size: int = Query(10, alias="pageSize"), user: Annotated[dict, Depends(current_user)] = None):
    where = and_(Conversation.user_id == user["id"], Conversation.is_deleted.is_(False))
    total = await session.scalar(select(func.count()).select_from(Conversation).where(where)) or 0
    rows = (await session.scalars(select(Conversation).where(where).order_by(desc(Conversation.updated_at)).offset((current - 1) * page_size).limit(page_size))).all()
    return envelope({"meta": {"current": current, "pageSize": page_size, "pages": math.ceil(total / page_size) if page_size else 0, "total": total}, "result": [_conversation_data(row) for row in rows]}, "Lấy danh sách cuộc trò chuyện thành công!")


@conversations.get("/cursor")
async def list_conversations_cursor(
    session: DB,
    cursor: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    user: Annotated[dict, Depends(current_user)] = None,
):
    """Keyset pagination for the user's conversation sidebar."""
    statement = select(Conversation).where(
        Conversation.user_id == user["id"],
        Conversation.is_deleted.is_(False),
    )
    if cursor:
        cursor_time, cursor_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                Conversation.updated_at < cursor_time,
                and_(Conversation.updated_at == cursor_time, Conversation.id < cursor_id),
            )
        )
    rows = (
        await session.scalars(
            statement.order_by(desc(Conversation.updated_at), desc(Conversation.id)).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        _encode_cursor(page_rows[-1].updated_at, page_rows[-1].id)
        if has_more and page_rows
        else None
    )
    return envelope(
        {
            "result": [_conversation_data(row) for row in page_rows],
            "pageInfo": {"nextCursor": next_cursor, "hasMore": has_more},
        },
        "Lấy danh sách cuộc trò chuyện thành công!",
    )


@conversations.put("/{conversation_id}")
async def update_conversation(conversation_id: str, body: UpdateConversationBody, session: DB, user: Annotated[dict, Depends(current_user)]):
    record = await owned_conversation(session, conversation_id, user)
    record.title, record.summary, record.updated_at = body.title, body.summary, datetime.now(timezone.utc)
    await session.commit(); await session.refresh(record)
    return envelope({"id": str(record.id), "userId": str(record.user_id), "title": record.title, "summary": record.summary, "createdAt": record.created_at, "updatedAt": record.updated_at, "deletedAt": record.deleted_at, "isDeleted": record.is_deleted}, "Cập nhật thông tin cuộc trò chuyện thành công!")


@conversations.delete("/{conversation_id}")
async def delete_conversation(conversation_id: str, session: DB, user: Annotated[dict, Depends(current_user)]):
    record = await owned_conversation(session, conversation_id, user)
    record.is_deleted, record.deleted_at = True, datetime.now(timezone.utc)
    await session.commit(); await session.refresh(record)
    return envelope({"id": str(record.id), "userId": str(record.user_id), "title": record.title, "summary": record.summary, "createdAt": record.created_at, "updatedAt": record.updated_at, "deletedAt": record.deleted_at, "isDeleted": record.is_deleted}, "Xóa cuộc trò chuyện thành công!")


@messages.get("/")
async def list_messages(session: DB, conversation_id: str = Query(alias="conversationId"), current: int = 1, page_size: int = Query(10, alias="pageSize"), user: Annotated[dict, Depends(current_user)] = None):
    await owned_conversation(session, conversation_id, user)
    where = Message.conversation_id == uuid.UUID(conversation_id)
    total = await session.scalar(select(func.count()).select_from(Message).where(where)) or 0
    rows = (await session.scalars(select(Message).where(where).order_by(desc(Message.created_at)).offset((current - 1) * page_size).limit(page_size))).all()
    result = [{"id": str(row.id), "content": row.content, "sender": row.sender, "thought": row.thought, "metadata": row.metadata_, "createdAt": row.created_at} for row in rows]
    return envelope({"meta": {"current": current, "pageSize": page_size, "pages": math.ceil(total / page_size) if page_size else 0, "total": total}, "result": result}, "Lấy danh sách tin nhắn thành công!")


@messages.get("/cursor")
async def list_messages_cursor(
    session: DB,
    conversation_id: str = Query(alias="conversationId"),
    cursor: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    user: Annotated[dict, Depends(current_user)] = None,
):
    """Load older messages without OFFSET or a COUNT(*) query."""
    conversation = await owned_conversation(session, conversation_id, user)
    statement = select(Message).where(Message.conversation_id == conversation.id)
    if cursor:
        cursor_time, cursor_id = _decode_cursor(cursor)
        statement = statement.where(
            or_(
                Message.created_at < cursor_time,
                and_(Message.created_at == cursor_time, Message.id < cursor_id),
            )
        )
    rows = (
        await session.scalars(
            statement.order_by(desc(Message.created_at), desc(Message.id)).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = (
        _encode_cursor(page_rows[-1].created_at, page_rows[-1].id)
        if has_more and page_rows
        else None
    )
    result = [
        {
            "id": str(row.id),
            "content": row.content,
            "sender": row.sender,
            "thought": row.thought,
            "metadata": row.metadata_,
            "createdAt": row.created_at,
        }
        for row in page_rows
    ]
    return envelope(
        {
            "result": result,
            "pageInfo": {"nextCursor": next_cursor, "hasMore": has_more},
        },
        "Lấy danh sách tin nhắn thành công!",
    )


@feedbacks.post("/message/{message_id}")
async def submit_feedback(message_id: str, body: FeedbackBody, session: DB, user: Annotated[dict, Depends(current_user)]):
    try:
        message = await session.scalar(select(Message).where(Message.id == uuid.UUID(message_id)))
    except ValueError:
        message = None
    if not message:
        raise ApiError(404, f"Nhắn tin ID {message_id} không tồn tại.", "Not Found")
    conversation = await session.scalar(select(Conversation).where(Conversation.id == message.conversation_id))
    if not conversation or str(conversation.user_id) != user["id"]:
        raise ApiError(403, "Bạn không có quyền đánh giá tin nhắn trong đoạn chat này.", "Forbidden")
    statement = insert(Feedback).values(message_id=message.id, user_id=uuid.UUID(user["id"]), is_like=body.is_like, reason=body.reason).on_conflict_do_update(index_elements=["message_id", "user_id"], set_={"is_like": body.is_like, "reason": body.reason, "updated_at": datetime.now(timezone.utc)}).returning(Feedback)
    feedback = (await session.execute(statement)).scalar_one()
    await session.commit()
    return envelope({"id": str(feedback.id), "messageId": str(feedback.message_id), "userId": str(feedback.user_id), "isLike": feedback.is_like, "reason": feedback.reason, "createdAt": feedback.created_at, "updatedAt": feedback.updated_at}, "Đã gửi phản hồi thành công!")
