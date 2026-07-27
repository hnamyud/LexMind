import secrets
from typing import Annotated

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select

from app.api.deps import DB, RedisDep
from app.core.config import Settings, get_settings
from app.core.responses import ApiError, envelope
from app.core.security import limit
from app.db.models import User
from app.schemas import SendResetEmailBody

router = APIRouter(prefix="/mail", tags=["Mail"])


@router.post("/reset-password")
async def send_reset_password(body: SendResetEmailBody, request: Request, session: DB, redis: RedisDep, settings: Annotated[Settings, Depends(get_settings)]):
    await limit(request, redis, "mail-reset", 60, 1)
    rate_key = f"reset_rate_limit:{body.email}"
    if int(await redis.get(rate_key) or 0) >= 5: raise ApiError(400, "Bạn đã gửi quá nhiều yêu cầu. Vui lòng thử lại sau.")
    if not await session.scalar(select(User).where(User.email == body.email)): raise ApiError(400, "Email không tồn tại trong hệ thống")
    otp = f"{secrets.randbelow(1_000_000):06d}"
    await redis.set(f"reset_otp:{body.email}", otp, ex=300); await redis.incr(rate_key); await redis.expire(rate_key, 900)
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await pool.enqueue_job("send_reset_password", body.email, otp, "[Chatbot Law] Yêu cầu đặt lại mật khẩu")
    await pool.aclose()
    return envelope(True, "Reset password code has sent!")
