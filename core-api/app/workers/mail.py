from datetime import datetime

import aiosmtplib
from email.message import EmailMessage

from app.core.config import get_settings


async def send_reset_password(_: dict, email: str, otp: str, subject: str) -> None:
    settings = get_settings()
    if not settings.email_host:
        raise RuntimeError("EMAIL_HOST is not configured")
    message = EmailMessage(); message["To"] = email; message["From"] = settings.mail_from; message["Subject"] = subject
    message.set_content(f"Mã OTP đặt lại mật khẩu của bạn là: {otp}\nMã có hiệu lực trong 5 phút.\n© {datetime.now().year} Chatbot Law")
    await aiosmtplib.send(message, hostname=settings.email_host, username=settings.email_user or None, password=settings.email_password or None, start_tls=True)


class WorkerSettings:
    functions = [send_reset_password]
    redis_settings = __import__("arq.connections", fromlist=["RedisSettings"]).RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
