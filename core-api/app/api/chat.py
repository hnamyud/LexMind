import json
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.api.deps import DB
from app.api.resources import owned_conversation
from app.core.config import Settings, get_settings
from app.core.responses import ApiError, envelope
from app.core.security import current_user, limit
from app.db.models import AIMetrics, Conversation, Message
from app.schemas import AskBody

router = APIRouter(prefix="/chat", tags=["Chat"])


def _metrics(message_id: uuid.UUID, value: dict) -> AIMetrics:
    return AIMetrics(
        message_id=message_id, model=value.get("model", "gemini-3-flash-preview"), ttft=value.get("ttft"), total_time=value.get("totalTime"),
        graph_query_time=value.get("graphQueryTime"), web_search_time=value.get("webSearchTime"), input_tokens=value.get("inputTokens"),
        output_tokens=value.get("outputTokens"), thinking_tokens=value.get("thinkingTokens"), tool_calls=value.get("toolCalls", 0),
        tool_call_details=value.get("toolCallDetails"), cost=value.get("cost"), error=value.get("error"), error_type=value.get("errorType"),
        cache_hit=value.get("cacheHit", False), cache_check_time=value.get("cacheCheckTime"), retry_count=0,
    )


async def _generate_title(session: DB, settings: Settings, conversation: Conversation, question: str, answer: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(settings.ai_base_url + "/conversations/generate-title", json={"user_message": question, "bot_message": answer}, headers={"INTERNAL-SECRET": settings.internal_secret})
            title = response.json().get("title", "").strip() if response.is_success else ""
        if title:
            conversation.title, conversation.updated_at = title, datetime.now(timezone.utc)
            await session.commit()
    except Exception:
        # Title generation is intentionally non-critical to the chat response.
        return


async def _stream_answer(question: str, conversation: Conversation, parent_id: uuid.UUID, session: DB, request: Request, settings: Settings):
    full_answer, thought, metadata, metrics, buffer = "", "", {}, None, ""
    yield f"data: {json.dumps({'type': 'info', 'conversationId': str(conversation.id)})}\n\n"
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", settings.ai_base_url + "/ask/stream", json={"question": question, "conversation_id": str(conversation.id)}, headers={"INTERNAL-SECRET": settings.internal_secret}) as upstream:
                upstream.raise_for_status()
                async for chunk in upstream.aiter_text():
                    if await request.is_disconnected():
                        return
                    buffer += chunk
                    lines = buffer.split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        if not line.strip():
                            continue
                        # The AI service emits one JSON object per line, without an SSE prefix.
                        yield f"data: {line}\n\n"
                        try:
                            item = json.loads(line)
                            if item.get("type") == "answer": full_answer += item.get("content", "")
                            elif item.get("type") == "thinking": thought += item.get("content", "")
                            elif item.get("type") == "metadata": metadata = item.get("content") or {}
                            elif item.get("type") == "metrics": metrics = item.get("content")
                        except json.JSONDecodeError:
                            continue
    except httpx.HTTPError:
        yield 'data: {"type":"error","content":"Mất kết nối với AI"}\n\n'
        return
    if buffer.strip():
        yield f"data: {buffer}\n\n"
    bot = Message(conversation_id=conversation.id, sender="bot", content=full_answer, thought=thought, parent_id=parent_id, metadata_=metadata)
    session.add(bot)
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()
    if metrics:
        session.add(_metrics(bot.id, metrics))
    await session.commit()
    yield f"data: {json.dumps({'type': 'message_id', 'messageId': str(bot.id)})}\n\n"
    count = await session.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)) or 0
    if count == 2 and full_answer.strip():
        await _generate_title(session, settings, conversation, question, full_answer)
    yield "data: [DONE]\n\n"


@router.post("/ask/stream")
async def ask_stream(body: AskBody, request: Request, session: DB, user: Annotated[dict, Depends(current_user)], settings: Annotated[Settings, Depends(get_settings)]):
    from app.db.session import redis_client
    await limit(request, redis_client, "chat-short", 60, 5, user)
    if body.conversation_id:
        conversation = await owned_conversation(session, body.conversation_id, user)
    else:
        conversation = Conversation(user_id=uuid.UUID(user["id"]), title=body.question[:50] + "...", summary="")
        session.add(conversation); await session.flush()
    user_message = Message(conversation_id=conversation.id, sender="user", content=body.question)
    session.add(user_message); conversation.updated_at = datetime.now(timezone.utc)
    await session.commit(); await session.refresh(conversation); await session.refresh(user_message)
    return StreamingResponse(_stream_answer(body.question, conversation, user_message.id, session, request, settings), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.post("/regenerate/{message_id}")
async def regenerate(message_id: str, request: Request, session: DB, user: Annotated[dict, Depends(current_user)], settings: Annotated[Settings, Depends(get_settings)]):
    from app.db.session import redis_client
    await limit(request, redis_client, "chat-default", 60, 5, user)
    try: bot = await session.scalar(select(Message).where(Message.id == uuid.UUID(message_id)))
    except ValueError: bot = None
    if not bot or bot.sender != "bot": raise ApiError(500, "Chỉ có thể tạo lại câu trả lời của AI.", "Internal Server Error")
    if not bot.parent_id: raise ApiError(500, "Không tìm thấy câu hỏi gốc để tạo lại.", "Internal Server Error")
    parent = await session.scalar(select(Message).where(Message.id == bot.parent_id)); conversation = await session.scalar(select(Conversation).where(Conversation.id == bot.conversation_id))
    await session.delete(bot); await session.commit()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            await client.delete(settings.ai_base_url + f"/conversations/{conversation.id}/checkpoints", headers={"INTERNAL-SECRET": settings.internal_secret})
    except httpx.HTTPError:
        pass
    return StreamingResponse(_stream_answer(parent.content, conversation, parent.id, session, request, settings), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


@router.get("/law-detail/{node_id}")
async def law_detail(node_id: str, limit_value: int = Query(25, alias="limit"), settings: Annotated[Settings, Depends(get_settings)] = None, user: Annotated[dict, Depends(current_user)] = None):
    safe_limit = min(max(limit_value, 1), 100)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(settings.ai_base_url + f"/law-detail/{node_id}", params={"limit": safe_limit})
    if response.status_code >= 400:
        raise ApiError(response.status_code, response.json())
    return envelope(response.json(), "Get Law Detail")
