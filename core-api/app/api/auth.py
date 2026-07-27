import secrets
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import SplitResult, urlsplit, urlunsplit

import bcrypt
import httpx
from authlib.common.errors import AuthlibBaseError
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.base_client.errors import MismatchingStateError, OAuthError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update

from app.api.deps import DB, RedisDep
from app.core.config import Settings, get_settings
from app.core.responses import ApiError, envelope
from app.core.security import current_user, issue_token, limit
from app.db.models import User
from app.schemas import ChangePasswordBody, LoginBody, OtpBody, RegisterBody, ResetPasswordBody

router = APIRouter(prefix="/auth", tags=["Auth"])


def _hash(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt(rounds=10)).decode()


def _valid(value: str, hashed: str) -> bool:
    return bcrypt.checkpw(value.encode(), hashed.encode())


def _payload(user: User) -> dict:
    return {"id": str(user.id), "email": user.email, "role": user.role}


def _google_oauth(settings: Settings):
    oauth = OAuth()
    oauth.register(
        "google",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    return oauth.google


def _origin(url: SplitResult) -> tuple[str, str, int]:
    default_port = 443 if url.scheme.lower() == "https" else 80
    return url.scheme.lower(), (url.hostname or "").lower(), url.port or default_port


def _canonical_google_login_url(request: Request, settings: Settings) -> str | None:
    """Keep local-development OAuth start and callback on one cookie origin.

    Browsers treat localhost and 127.0.0.1 as different cookie hosts. If the
    frontend starts OAuth through one while GOOGLE_REDIRECT_URI uses the other,
    Authlib cannot recover the state at callback time. Redirecting the start
    endpoint fixes that locally without disabling OAuth state/CSRF validation.

    Never canonicalize a production request here. Behind a reverse proxy,
    ``request.url`` can contain the internal HTTP origin even though the browser
    is already using the configured public HTTPS origin. Canonicalizing that
    request would redirect ``/auth/google/login`` back to itself forever.
    """
    if settings.is_production:
        return None

    current = urlsplit(str(request.url))
    callback = urlsplit(settings.google_redirect_uri)
    local_hosts = {"localhost", "127.0.0.1"}
    if current.hostname not in local_hosts or callback.hostname not in local_hosts:
        return None
    if _origin(current) == _origin(callback):
        return None
    return urlunsplit((callback.scheme, callback.netloc, current.path, "", ""))


def _set_refresh(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        "refresh_token", token, httponly=True, secure=settings.is_production,
        samesite="none" if settings.is_production else "lax",
        max_age=int(__import__("app.core.security", fromlist=["_duration"])._duration(settings.jwt_refresh_expired).total_seconds()),
    )


@router.post("/register")
async def register(body: RegisterBody, session: DB):
    existing = await session.scalar(select(User).where(User.email == body.email))
    if existing:
        raise ApiError(400, f"Email: {body.email} đã tồn tại")
    user = User(full_name=body.name, email=body.email, password=_hash(body.password), role="USER")
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return envelope({"id": str(user.id), "createdAt": user.created_at}, "Đăng ký thành công!")


@router.post("/login")
async def login(body: LoginBody, response: Response, session: DB, settings: Annotated[Settings, Depends(get_settings)]):
    user = await session.scalar(select(User).where(User.email == body.email))
    if not user or not _valid(body.password, user.password):
        raise ApiError(401, "Invalid Username/Password !", "Unauthorized")
    data = _payload(user)
    refresh = issue_token(data, settings.jwt_refresh_secret, settings.jwt_refresh_expired)
    user.refresh_token = refresh
    await session.commit()
    _set_refresh(response, refresh, settings)
    return envelope({"accessToken": issue_token(data, settings.jwt_access_secret, settings.jwt_access_expired), "user": data}, "Đăng nhập thành công!")


@router.post("/logout")
async def logout(response: Response, session: DB, user: Annotated[dict, Depends(current_user)], settings: Annotated[Settings, Depends(get_settings)]):
    await session.execute(update(User).where(User.id == user["id"]).values(refresh_token=None))
    await session.commit()
    kwargs = {"httponly": True, "secure": settings.is_production, "samesite": "none" if settings.is_production else "lax", "path": "/"}
    response.delete_cookie("refresh_token", **kwargs)
    response.delete_cookie("access_token", **kwargs)
    return envelope({"message": "Đăng xuất thành công!", "loggedOut": True, "timestamp": datetime.now(timezone.utc)}, "Đăng xuất thành công!")


@router.get("/profile")
async def profile(session: DB, user: Annotated[dict, Depends(current_user)]):
    record = await session.scalar(select(User).where(User.id == user["id"]))
    if not record:
        raise ApiError(401, "Invalid token!", "Unauthorized")
    return envelope({"id": str(record.id), "fullName": record.full_name, "email": record.email, "role": record.role, "createdAt": record.created_at}, "Lấy thông tin user thành công!")


@router.get("/refresh")
async def refresh(request: Request, response: Response, session: DB, settings: Annotated[Settings, Depends(get_settings)]):
    token = request.cookies.get("refresh_token")
    try:
        jwt_payload = __import__("jwt").decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
        record = await session.scalar(select(User).where(User.refresh_token == token))
        if not record:
            raise ValueError
    except Exception:
        raise ApiError(400, "Refresh token không hợp lệ!")
    data = {key: jwt_payload[key] for key in ("id", "email", "role")}
    refresh_token = issue_token(data, settings.jwt_refresh_secret, settings.jwt_refresh_expired)
    record.refresh_token = refresh_token
    await session.commit()
    _set_refresh(response, refresh_token, settings)
    return envelope({"accessToken": issue_token(data, settings.jwt_access_secret, settings.jwt_access_expired), "user": data}, "Làm mới token thành công!")


@router.post("/verify-otp")
async def verify_otp(body: OtpBody, request: Request, redis: RedisDep):
    await limit(request, redis, "verify-otp", 60, 3)
    attempts_key, otp_key = f"reset_otp_attempts:{body.email}", f"reset_otp:{body.email}"
    if int(await redis.get(attempts_key) or 0) >= 5:
        await redis.delete(attempts_key, otp_key)
        raise ApiError(400, "Bạn đã nhập sai OTP quá nhiều lần! Vui lòng yêu cầu OTP mới.")
    if await redis.get(otp_key) != body.otp:
        await redis.incr(attempts_key); await redis.expire(attempts_key, 300)
        raise ApiError(400, "OTP không hợp lệ hoặc đã hết hạn!" if not await redis.get(otp_key) else "OTP không hợp lệ!")
    await redis.delete(attempts_key)
    return envelope({"message": "Xác thực OTP thành công!"}, "Xác thực OTP thành công!")


@router.post("/reset-password")
async def reset_password(body: ResetPasswordBody, request: Request, redis: RedisDep, session: DB):
    await limit(request, redis, "reset-password", 60, 3)
    if await redis.get(f"reset_otp:{body.email}") != body.otp:
        raise ApiError(400, "OTP không hợp lệ hoặc đã hết hạn!")
    user = await session.scalar(select(User).where(User.email == body.email))
    if not user:
        raise ApiError(400, "Không tìm thấy tài khoản!")
    user.password = _hash(body.new_password)
    await redis.delete(f"reset_otp:{body.email}")
    await session.commit()
    return envelope(None, "Đặt lại mật khẩu thành công!")


@router.post("/change-password")
async def change_password(body: ChangePasswordBody, session: DB, user: Annotated[dict, Depends(current_user)]):
    record = await session.scalar(select(User).where(User.id == user["id"]))
    if not record or not _valid(body.old_password, record.password):
        raise ApiError(400, "Mật khẩu cũ không đúng")
    if _valid(body.new_password, record.password):
        raise ApiError(400, "Mật khẩu mới không được giống mật khẩu cũ")
    record.password = _hash(body.new_password)
    await session.commit()
    return envelope({"id": str(record.id), "email": record.email}, "Thay đổi mật khẩu thành công!")


@router.get("/google/login")
async def google_login(request: Request, settings: Annotated[Settings, Depends(get_settings)]):
    if not settings.google_client_id or not settings.google_client_secret or not settings.google_redirect_uri:
        raise ApiError(500, "Google OAuth chưa được cấu hình")
    canonical_url = _canonical_google_login_url(request, settings)
    if canonical_url:
        return RedirectResponse(canonical_url, status_code=302)
    return await _google_oauth(settings).authorize_redirect(request, settings.google_redirect_uri)


@router.get("/google/callback")
async def google_callback(request: Request, session: DB, settings: Annotated[Settings, Depends(get_settings)]):
    google = _google_oauth(settings)
    try:
        token = await google.authorize_access_token(request)
        info = token.get("userinfo") or await google.userinfo(token=token)
    except MismatchingStateError as exc:
        raise ApiError(
            400,
            "Phiên đăng nhập Google không khớp hoặc đã hết hạn. "
            "Vui lòng bắt đầu lại từ cùng địa chỉ Core API.",
        ) from exc
    except OAuthError as exc:
        raise ApiError(400, "Google không chấp nhận yêu cầu đăng nhập. Vui lòng thử lại.") from exc
    except (httpx.HTTPError, AuthlibBaseError) as exc:
        raise ApiError(502, "Không thể xác thực tài khoản với Google. Vui lòng thử lại.") from exc

    if not info.get("email"):
        raise ApiError(400, "Google không trả về địa chỉ email cho tài khoản này.")
    user = await session.scalar(select(User).where(User.email == info["email"]))
    if not user:
        user = User(full_name=info.get("name"), email=info["email"], password=_hash(secrets.token_urlsafe(24)), role="USER"); session.add(user); await session.flush()
    data = _payload(user); user.refresh_token = issue_token(data, settings.jwt_refresh_secret, settings.jwt_refresh_expired); await session.commit()
    response = RedirectResponse(
        (settings.browser_redirect_uri or settings.fe_domain + "?token=")
        + issue_token(data, settings.jwt_access_secret, settings.jwt_access_expired),
        status_code=302,
    )
    _set_refresh(response, user.refresh_token, settings)
    return response
