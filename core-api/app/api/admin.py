import time
from datetime import datetime, timedelta, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select, text

from app.api.deps import DB, RedisDep
from app.core.config import Settings, get_settings
from app.core.responses import envelope
from app.core.security import admin_user
from app.db.models import AIMetrics, Conversation, Feedback, Message, User

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(admin_user)])


def page(value: int | None, default: int) -> int:
    return value if value and value > 0 else default


@router.get("/users")
async def users(session: DB, page_no: int = 1, limit: int = 20, role: str | None = None, search: str | None = None, include_deleted: bool = False, user: dict = Depends(admin_user)):
    stmt = select(User)
    if role: stmt = stmt.where(User.role == role)
    if search: stmt = stmt.where((User.email.ilike(f"%{search}%")) | (User.full_name.ilike(f"%{search}%")))
    if not include_deleted: stmt = stmt.where(User.deleted_at.is_(None))
    records = (await session.scalars(stmt.order_by(desc(User.created_at)).offset((page_no - 1) * limit).limit(limit))).all()
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    data = []
    for record in records:
        conversations = await session.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == record.id)) or 0
        feedback_count = await session.scalar(select(func.count()).select_from(Feedback).where(Feedback.user_id == record.id)) or 0
        last_active = await session.scalar(select(Message.created_at).join(Conversation, Message.conversation_id == Conversation.id).where(Conversation.user_id == record.id).order_by(desc(Message.created_at)).limit(1))
        data.append({"id": str(record.id), "email": record.email, "fullName": record.full_name, "role": record.role, "createdAt": record.created_at, "deletedAt": record.deleted_at, "stats": {"conversationCount": conversations, "feedbackCount": feedback_count, "lastActiveAt": last_active}})
    return envelope({"data": data, "total": total, "page": page_no, "limit": limit}, "Lấy danh sách users thành công")


@router.get("/users/{user_id}")
async def user_detail(user_id: str, session: DB, user: dict = Depends(admin_user)):
    record = await session.scalar(select(User).where(User.id == user_id))
    if not record: return envelope(None, "Lấy chi tiết user thành công")
    conversation_count = await session.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == record.id)) or 0
    feedback_count = await session.scalar(select(func.count()).select_from(Feedback).where(Feedback.user_id == record.id)) or 0
    return envelope({"id": str(record.id), "email": record.email, "fullName": record.full_name, "role": record.role, "createdAt": record.created_at, "deletedAt": record.deleted_at, "stats": {"totalConversations": conversation_count, "totalFeedbacks": feedback_count}}, "Lấy chi tiết user thành công")


@router.get("/conversations")
async def conversation_list(session: DB, page_no: int = 1, limit: int = 20, user_id: str | None = None, user: dict = Depends(admin_user)):
    stmt = select(Conversation).where(Conversation.is_deleted.is_(False))
    if user_id: stmt = stmt.where(Conversation.user_id == user_id)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (await session.scalars(stmt.order_by(desc(Conversation.created_at)).offset((page_no - 1) * limit).limit(limit))).all()
    data = []
    for row in rows:
        count = await session.scalar(select(func.count()).select_from(Message).where(Message.conversation_id == row.id)) or 0
        data.append({"id": str(row.id), "title": row.title, "userId": str(row.user_id), "messageCount": count, "createdAt": row.created_at, "updatedAt": row.updated_at})
    return envelope({"data": data, "total": total, "page": page_no, "limit": limit}, "Lấy danh sách conversations thành công")


@router.get("/conversations/stats")
async def conversation_stats(session: DB, user: dict = Depends(admin_user)):
    total = await session.scalar(select(func.count()).select_from(Conversation).where(Conversation.is_deleted.is_(False))) or 0
    messages = await session.scalar(select(func.count()).select_from(Message)) or 0
    return envelope({"totalConversations": total, "totalMessages": messages, "avgMessagesPerConversation": round(messages / total) if total else 0, "conversationsPerDay": [], "topUsers": []}, "Lấy thống kê conversations thành công")


@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str, session: DB, user: dict = Depends(admin_user)):
    record = await session.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not record: return envelope(None, "Lấy chi tiết conversation thành công")
    rows = (await session.scalars(select(Message).where(Message.conversation_id == record.id).order_by(Message.created_at))).all()
    return envelope({"id": str(record.id), "title": record.title, "userId": str(record.user_id), "createdAt": record.created_at, "messages": [{"id": str(row.id), "sender": row.sender, "content": row.content, "thought": row.thought, "metadata": row.metadata_, "createdAt": row.created_at} for row in rows]}, "Lấy chi tiết conversation thành công")


@router.get("/ai/performance")
async def performance(session: DB, user: dict = Depends(admin_user)):
    total, average = (await session.execute(select(func.count(AIMetrics.id), func.avg(AIMetrics.total_time)))).one()
    return envelope({"overview": {"avgResponseTime": round(average or 0), "totalMessages": total or 0, "p50ResponseTime": None, "p95ResponseTime": None, "p99ResponseTime": None, "avgTTFT": 0, "totalCost": 0, "avgCostPerMessage": 0}, "modelDistribution": [], "tokenUsage": {"totalInputTokens": 0, "totalOutputTokens": 0, "totalThinkingTokens": 0, "avgInputTokensPerMessage": 0, "avgOutputTokensPerMessage": 0}}, "Lấy metrics hiệu suất AI thành công")


@router.get("/ai/quality")
async def quality(session: DB, user: dict = Depends(admin_user)):
    likes = await session.scalar(select(func.count()).select_from(Feedback).where(Feedback.is_like.is_(True))) or 0; total = await session.scalar(select(func.count()).select_from(Feedback)) or 0
    return envelope({"overview": {"totalFeedbacks": total, "likeCount": likes, "dislikeCount": total - likes, "likeRatio": round(likes / total, 2) if total else 0, "qualityScore": round(likes * 100 / total) if total else 0}, "timeSeries": [], "dislikeReasons": [], "feedbackByResponseTime": []}, "Lấy metrics chất lượng AI thành công")


@router.get("/ai/cache")
async def cache(session: DB, user: dict = Depends(admin_user)):
    hits = await session.scalar(select(func.count()).select_from(AIMetrics).where(AIMetrics.cache_hit.is_(True))) or 0; total = await session.scalar(select(func.count()).select_from(AIMetrics)) or 0
    return envelope({"overview": {"totalQueries": total, "cacheHits": hits, "cacheMisses": total - hits, "hitRatePercent": round(hits * 100 / total, 2) if total else 0, "avgTimeSavedMs": 0, "totalTimeSavedMs": 0}, "responseTimeComparison": {"cached": {"avg": 0, "p50": None, "p95": None}, "nonCached": {"avg": 0, "p50": None, "p95": None}}, "timeSeries": []}, "Lấy cache analytics thành công")


@router.get("/health")
async def health(
    session: DB,
    redis: RedisDep,
    settings: Annotated[Settings, Depends(get_settings)],
    user: dict = Depends(admin_user),
):
    """Preserve the established health-check response contract."""
    async def database_health() -> dict:
        started = time.perf_counter()
        try:
            await session.execute(text("SELECT 1"))
            return {"status": "up", "responseTime": round((time.perf_counter() - started) * 1000)}
        except Exception as exc:
            return {"status": "down", "responseTime": round((time.perf_counter() - started) * 1000), "error": str(exc)}

    async def redis_health() -> dict:
        started = time.perf_counter()
        try:
            result = await redis.ping()
            if result:
                return {"status": "up", "responseTime": round((time.perf_counter() - started) * 1000)}
            return {"status": "degraded", "responseTime": round((time.perf_counter() - started) * 1000), "error": "Unexpected Redis response"}
        except Exception as exc:
            return {"status": "down", "responseTime": round((time.perf_counter() - started) * 1000), "error": str(exc)}

    async def ai_health() -> dict:
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(settings.ai_base_url + "/health")
                response.raise_for_status()
            return {"status": "up", "responseTime": round((time.perf_counter() - started) * 1000)}
        except Exception as exc:
            return {"status": "down", "responseTime": round((time.perf_counter() - started) * 1000), "error": str(exc)}

    database, ai_service, redis_service = await database_health(), await ai_health(), await redis_health()
    services = {"database": database, "aiService": ai_service, "redis": redis_service}
    statuses = [service["status"] for service in services.values()]
    status = "healthy" if all(value == "up" for value in statuses) else "unhealthy" if "down" in statuses else "degraded"
    return envelope(
        {"status": status, "timestamp": datetime.now(timezone.utc), "services": services},
        "Kiểm tra sức khỏe hệ thống thành công",
    )


@router.get("/system/stats")
async def system_stats(session: DB, user: dict = Depends(admin_user)):
    """Return the established enhanced system-statistics response."""
    now = datetime.now(timezone.utc)
    day_ago, week_ago, month_ago = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)

    async def active_users(since: datetime) -> int:
        statement = (
            select(func.count(func.distinct(Conversation.user_id)))
            .select_from(Conversation)
            .join(Message, Message.conversation_id == Conversation.id)
            .where(Message.created_at >= since)
        )
        return await session.scalar(statement) or 0

    active_24h = await active_users(day_ago)
    active_7d = await active_users(week_ago)
    active_30d = await active_users(month_ago)
    messages_24h = await session.scalar(select(func.count()).select_from(Message).where(Message.created_at >= day_ago)) or 0
    messages_7d = await session.scalar(select(func.count()).select_from(Message).where(Message.created_at >= week_ago)) or 0
    messages_30d = await session.scalar(select(func.count()).select_from(Message).where(Message.created_at >= month_ago)) or 0
    bot_24h = await session.scalar(select(func.count()).select_from(Message).where(Message.created_at >= day_ago, Message.sender == "bot")) or 0
    bot_7d = await session.scalar(select(func.count()).select_from(Message).where(Message.created_at >= week_ago, Message.sender == "bot")) or 0
    errors_24h = await session.scalar(select(func.count()).select_from(AIMetrics).where(AIMetrics.created_at >= day_ago, AIMetrics.error.is_not(None))) or 0
    errors_7d = await session.scalar(select(func.count()).select_from(AIMetrics).where(AIMetrics.created_at >= week_ago, AIMetrics.error.is_not(None))) or 0
    slow_24h = await session.scalar(select(func.count()).select_from(AIMetrics).where(AIMetrics.created_at >= day_ago, AIMetrics.total_time > 5000)) or 0
    metrics_count, average_response_time = (await session.execute(select(func.count(AIMetrics.id), func.avg(AIMetrics.total_time)).where(AIMetrics.created_at >= day_ago))).one()

    error_24h_percentage = round(errors_24h * 100 / bot_24h, 2) if bot_24h else 0
    error_7d_percentage = round(errors_7d * 100 / bot_7d, 2) if bot_7d else 0
    slow_percentage = round(slow_24h * 100 / metrics_count, 2) if metrics_count else 0
    data = {
        "activeUsers": {"last24h": active_24h, "last7d": active_7d, "last30d": active_30d},
        "requestRate": {"messagesLast24h": messages_24h, "messagesLast7d": messages_7d, "avgMessagesPerDay": round(messages_30d / 30)},
        "errorRate": {"last24h": {"total": errors_24h, "percentage": error_24h_percentage}, "last7d": {"total": errors_7d, "percentage": error_7d_percentage}},
        "performance": {"avgResponseTime": round(average_response_time or 0), "slowRequests24h": slow_24h, "slowRequestsPercentage": slow_percentage},
    }
    return envelope(data, "Lấy thống kê hệ thống thành công")


@router.get("/feedbacks")
async def feedback_list(session: DB, page_no: int = 1, limit: int = 20, user: dict = Depends(admin_user)):
    total = await session.scalar(select(func.count()).select_from(Feedback)) or 0; rows = (await session.scalars(select(Feedback).order_by(desc(Feedback.created_at)).offset((page_no - 1) * limit).limit(limit))).all()
    return envelope({"data": [{"id": str(row.id), "messageId": str(row.message_id), "userId": str(row.user_id), "isLike": row.is_like, "reason": row.reason, "createdAt": row.created_at, "updatedAt": row.updated_at} for row in rows], "total": total, "page": page_no, "limit": limit, "stats": {"totalLikes": 0, "totalDislikes": 0, "likeRatio": 0}}, "Lấy danh sách feedbacks thành công")


@router.get("/feedbacks/analytics")
async def feedback_analytics(session: DB, user: dict = Depends(admin_user)):
    return await quality(session, user)


@router.get("/ai/errors")
async def ai_errors(session: DB, page_no: int = 1, limit: int = 20, user: dict = Depends(admin_user)):
    total = await session.scalar(select(func.count()).select_from(AIMetrics).where(AIMetrics.error.is_not(None))) or 0
    return envelope({"data": [], "total": total, "errorsByType": []}, "Lấy danh sách lỗi AI thành công")
