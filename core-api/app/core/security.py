import time
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis

from app.core.config import Settings, get_settings
from app.core.responses import ApiError

bearer = HTTPBearer(auto_error=False)
JWT_ISSUER = "Chatbot Law Core API"


def _duration(value: str) -> timedelta:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        return timedelta(seconds=int(value[:-1]) * units[value[-1]])
    except (ValueError, KeyError, IndexError):
        return timedelta(days=1)


def issue_token(user: dict, secret: str, expires: str) -> str:
    payload = {
        "sub": "Access token",
        "iss": JWT_ISSUER,
        **user,
        "exp": datetime.now(UTC) + _duration(expires),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict:
    if not credentials:
        raise ApiError(401, "Invalid token!", "Unauthorized")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_access_secret, algorithms=["HS256"])
        return {key: payload[key] for key in ("id", "email", "role")}
    except (jwt.InvalidTokenError, KeyError):
        raise ApiError(401, "Invalid token!", "Unauthorized")


def admin_user(user: Annotated[dict, Depends(current_user)]) -> dict:
    if user["role"] != "ADMIN":
        raise ApiError(403, "Bạn không có quyền thực hiện hành động này!", "Forbidden")
    return user


async def limit(request: Request, redis: Redis, name: str, ttl: int, maximum: int, user: dict | None = None) -> None:
    if user and user.get("role") == "ADMIN":
        return
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0]
    tracker = f"{forwarded or request.client.host}:{user['id'] if user else 'anonymous'}"
    key = f"rate:{name}:{tracker}:{int(time.time() // ttl)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, ttl)
    if count > maximum:
        raise ApiError(429, "ThrottlerException: Too Many Requests", "Too Many Requests")
